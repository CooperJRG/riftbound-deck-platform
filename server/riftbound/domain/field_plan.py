"""What you will actually face, and what it costs you.

A win rate against "the field" is an average over an imaginary opponent. This module
replaces it with the real one: the field is a distribution of legends in known
proportions, and a deck meets each of them as often as that proportion says. Two things
fall out that nothing else in this codebase could compute before the matchup table
arrived.

**Expected win rate.** ``sum(share(opponent) x winrate(you, opponent))`` -- how a legend
does against the field it is actually in, rather than against everything equally. It
disagrees with the overall rate whenever a legend's good matchups are rare and its bad
ones are popular, which is precisely the situation a player wants warned about.

**A boarding order.** The matchup you should prepare for is not the one you lose hardest;
it is the one that costs you the most, which is ``share x (winrate - 0.5)``. Losing 40%
to 11% of the field costs six times what losing 20% to 1% does, and only one of those is
worth three sideboard slots.

Three disciplines, and the third is the one worth being stubborn about.

**One population.** The shares here come from the *matchup source's own* match counts,
never from this project's published-list share. Those are different populations measured
over different windows -- our archive spans two years of decklists, the matrix spans one
set's recorded matches -- and multiplying a share from one by a rate from the other
produces a number that is true of neither. It is the same rule ``matchups.py`` follows in
refusing to average the two win rates.

**Coverage, reported.** Only rated matchups contribute, so the sum is renormalised over
the share they cover and :attr:`FieldOutlook.coverage` says how much of the field that
was. An expected win rate computed over 60% of the field is a different claim from one
computed over 95%, and hiding the difference makes the weaker number look like the
stronger one.

**No card is ever claimed to answer a matchup.** There is no card-level matchup data in
any source available here -- the matrix is legend against legend, and nothing published
says which card won which game. So this module ranks *matchups*, which the data supports,
and then shows what the opponent actually plays and what lists like yours actually hold
in reserve. Both are facts. "Play this against Kai'Sa" would not be, and inventing it is
how a tool starts confidently making things up.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .cards import Catalog
from .legend_index import LegendIndex
from .matchups import MatchupTable

#: A matchup must cost at least this much expected win rate before it is worth a
#: sideboard slot. 0.5 points of the whole field's win rate -- below it, the swing is
#: smaller than the interval on the matchup that produced it, so acting on the order
#: would be acting on noise.
MIN_SWING = 0.005

#: How much of an opponent's list to show as "what they play". Enough to recognise the
#: deck, short enough to read before game two starts.
THREATS_SHOWN = 8


@dataclass(frozen=True)
class FieldMatchup:
    """One opponent you will actually meet, weighted by how often."""

    opponent_id: str
    opponent_name: str
    image_url: str
    #: Share of the recorded field this opponent represents, 0-1.
    share: float
    win_rate: float
    interval_low: float
    interval_high: float
    matches: int
    shown: bool
    separated: bool

    @property
    def swing(self) -> float:
        """Expected win rate gained or lost to this opponent, across the whole field.

        Negative is ground lost. Zero when the matchup is unrated -- an unknown matchup
        contributes nothing rather than a guess of even.
        """
        if not self.shown:
            return 0.0
        return self.share * (self.win_rate - 0.5)

    @property
    def worth_boarding(self) -> bool:
        """A losing matchup big enough to be worth spending slots on."""
        return self.shown and self.swing <= -MIN_SWING

    def describe(self) -> str:
        if not self.shown:
            return f"{self.share:.1%} of the field, matchup not rated yet"
        return (
            f"{self.share:.1%} of the field, {self.win_rate:.1%} win rate "
            f"({self.swing * 100:+.1f} pts)"
        )


@dataclass(frozen=True)
class FieldOutlook:
    """How a legend sits in the field it is actually in."""

    legend_id: str
    name: str
    #: Share-weighted win rate over the *rated* part of the field, 0-1.
    expected_win_rate: float
    #: The legend's own overall rate, for comparison. The two disagree when a legend's
    #: bad matchups are the popular ones, which is the whole point of computing both.
    overall_win_rate: float
    #: Share of the field whose matchup is rated. The denominator behind the number
    #: above, reported so a thin one cannot pass as a thorough one.
    coverage: float
    shown: bool
    matchups: tuple[FieldMatchup, ...] = ()

    @property
    def field_delta(self) -> float:
        """Expected minus overall. Negative means the field is worse than average for it."""
        return self.expected_win_rate - self.overall_win_rate

    def boarding_order(self) -> tuple[FieldMatchup, ...]:
        """The matchups worth sideboard slots, most expensive first."""
        return tuple(
            sorted(
                (m for m in self.matchups if m.worth_boarding),
                key=lambda m: (m.swing, -m.share),
            )
        )

    def describe(self) -> str:
        if not self.shown:
            return "Not enough rated matchups to place this legend in the field."
        return (
            f"{self.expected_win_rate:.1%} expected against the field as it is played, "
            f"over {self.coverage:.0%} of it"
        )


def field_shares(table: MatchupTable) -> dict[str, float]:
    """How much of the recorded field each legend is, by matches played.

    Matches rather than distinct players or published lists: it is the denominator the
    matchup rates were themselves computed over, so a share and a rate multiplied
    together stay inside one population. Mirrors are included in a legend's own match
    count upstream, which is correct here -- you do meet your own legend.
    """
    totals = {r.legend_id: float(r.matches) for r in table.records if r.matches > 0}
    grand = sum(totals.values())
    if grand <= 0:
        return {}
    return {legend_id: count / grand for legend_id, count in totals.items()}


def field_outlook(
    legend_id: str, *, table: MatchupTable, catalog: Catalog
) -> FieldOutlook:
    """Place one legend in the field, weighted by what that field actually plays."""
    record = table.record(legend_id)
    card = catalog.get(legend_id)
    name = record.name if record else (card.name if card else legend_id)
    shares = field_shares(table)

    rows: list[FieldMatchup] = []
    weighted = 0.0
    covered = 0.0
    for row in table.for_legend(legend_id):
        share = shares.get(row.opponent_id, 0.0)
        opponent = catalog.get(row.opponent_id)
        rows.append(
            FieldMatchup(
                opponent_id=row.opponent_id,
                opponent_name=row.opponent_name,
                image_url=opponent.image_url if opponent else "",
                share=share,
                win_rate=row.win_rate,
                interval_low=row.interval_low,
                interval_high=row.interval_high,
                matches=row.matches,
                shown=row.shown,
                separated=row.separated,
            )
        )
        if row.shown and share > 0:
            weighted += share * row.win_rate
            covered += share

    # Renormalised over what is rated, never over the whole field: dividing by the whole
    # would silently score every unrated opponent as a 0% matchup.
    expected = weighted / covered if covered > 0 else 0.0
    return FieldOutlook(
        legend_id=legend_id,
        name=name,
        expected_win_rate=expected,
        overall_win_rate=record.win_rate if record and record.shown else 0.0,
        coverage=covered,
        shown=covered > 0,
        matchups=tuple(sorted(rows, key=lambda m: -m.share)),
    )


# -- sideboard planning -------------------------------------------------------


@dataclass(frozen=True)
class Threat:
    """A card the opponent reliably brings. Not a card you should answer with."""

    card_id: str
    name: str
    image_url: str
    #: Share of that legend's published lists running it, 0-1.
    play_rate: float


@dataclass(frozen=True)
class MatchupPlan:
    """One matchup worth preparing for, and what is known about it.

    Deliberately does **not** carry "cards that beat this deck". No source available
    here records which card won which game, so such a list could only be invented. What
    it carries instead is what the opponent reliably plays -- which is a fact, and is
    what a player needs in order to choose an answer themselves.
    """

    matchup: FieldMatchup
    threats: tuple[Threat, ...]

    def describe(self) -> str:
        return (
            f"{self.matchup.opponent_name}: {self.matchup.describe()}"
        )


def _threats(
    opponent_id: str, *, index: LegendIndex, catalog: Catalog, limit: int = THREATS_SHOWN
) -> tuple[Threat, ...]:
    """The cards that opponent's published lists most reliably run.

    Read from the legend index, which is already score-weighted and scoped to the
    current era -- so this reports what the *good* current lists play rather than what
    the whole archive ever played. Runes are dropped: every deck runs twelve, so they
    identify nothing about the opponent.
    """
    profile = index.get(opponent_id)
    if profile is None:
        return ()
    ranked = sorted(profile.play_rate.items(), key=lambda kv: -kv[1])
    out: list[Threat] = []
    for card_id, rate in ranked:
        card = catalog.get(card_id)
        if card is None or card.card_type == "Rune" or card.card_id == opponent_id:
            continue
        out.append(
            Threat(
                card_id=card_id,
                name=card.name,
                image_url=card.image_url,
                play_rate=rate,
            )
        )
        if len(out) >= limit:
            break
    return tuple(out)


def sideboard_plan(
    legend_id: str,
    *,
    table: MatchupTable,
    index: LegendIndex,
    catalog: Catalog,
    limit: int = 4,
) -> tuple[FieldOutlook, tuple[MatchupPlan, ...]]:
    """Which matchups to spend sideboard slots on, most expensive first.

    Returns the outlook as well as the plans, because the plans are meaningless without
    it: "board for Kai'Sa" is only advice if you can also see that Kai'Sa is 5% of the
    field and you are 43% into it.
    """
    outlook = field_outlook(legend_id, table=table, catalog=catalog)
    plans = tuple(
        MatchupPlan(matchup=row, threats=_threats(row.opponent_id, index=index, catalog=catalog))
        for row in outlook.boarding_order()[:limit]
    )
    return outlook, plans


def rank_by_field(
    legend_ids: Sequence[str], *, table: MatchupTable, catalog: Catalog
) -> dict[str, FieldOutlook]:
    """Outlooks for many legends at once, for the picker's ordering."""
    return {
        legend_id: field_outlook(legend_id, table=table, catalog=catalog)
        for legend_id in legend_ids
    }


def outlook_summary(outlooks: Mapping[str, FieldOutlook]) -> str:
    rated = [o for o in outlooks.values() if o.shown]
    if not rated:
        return "No legend has enough rated matchups to place in the field yet."
    return f"{len(rated)} of {len(outlooks)} legends placed against the current field."
