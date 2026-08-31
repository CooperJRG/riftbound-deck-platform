"""Legend versus legend: who beats whom, and when we are willing to say so.

``meta_trends/performance.py`` measures how a deck fares against *the field*. It closes
by naming the thing it cannot do:

    "What is genuinely unavailable: the opponent. Matchup tables are out of scope
    permanently unless a source begins publishing pairings, and no model manufactures
    them."

This module exists because a source began publishing them. Riftools aggregates official
UVS match records into a 48-legend matrix -- 1,740 ordered cells over 25,622 non-mirror
matches -- and that is a different question from every other number in this codebase.
Presence says what is played. Performance says what wins. A matchup says *what beats
what*, which is the only one of the three that can tell a player their deck is fine and
their week was not.

Four disciplines, three carried from ``performance.py`` because the failure modes are
identical and one specific to a table somebody else computed.

**A confidence interval, not a point.** Wilson, reusing ``performance.wilson`` rather
than a second copy -- a matchup cell is a smaller sample than an archetype rate, so the
interval matters more here, not less.

**Refusal, with the threshold named.** Below :data:`MIN_MATCHES` a cell churns by more
than the effect it is trying to report. The counts stay populated when the rate is
withheld, so a client shows "18 matches so far" rather than a blank.

**Events, not just matches.** A matchup seen forty times at one tournament describes
that tournament. :data:`MIN_EVENTS` is the same guard ``performance.py`` applies for the
same reason.

**The aggregate is not ours.** Every other module under ``domain/`` computes its numbers
from records this project normalised. These arrive already summed, from matches we
cannot inspect, so they cannot be recomputed or audited row by row -- only checked for
internal consistency (see :func:`symmetry_errors`) and labelled honestly.
:class:`MatchupBasis` carries the source, the window and the sample in the response, so
the provenance is data rather than a footnote a client can forget to render.

Deliberately **not** merged with ``performance.py``'s win rate. The two measure
different populations over different windows from different sources: ours is a rate
among published lists in our ban era, this is a rate among recorded matches in a set
window. Averaging them would produce a number that is true of nothing.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from .cards import Catalog
from .meta_trends.performance import wilson

#: Decisive matches a cell needs before its rate is published.
#:
#: Measured, not chosen. Riftools ships per-tournament payloads beside the aggregate, so
#: the split-half test ``performance.py`` used for its own floor runs here too: split the
#: 32 events at random, rebuild the matrix on each half, and compare the cells that clear
#: the floor on both sides. 200 resamples per floor, six seeds:
#:
#:   floor        10     15     20     25     30     40     50     75    100
#:   disagree   10.6pt  9.1pt  8.1pt  7.4pt  6.9pt  6.3pt  5.9pt  5.3pt  4.9pt
#:   cells         426    298    215    167    133     90     65     36     20
#:
#: The curve has a knee at 30. Below it a cell moves by around ten points between two
#: halves of the same season -- which for a matchup is the whole distance between
#: "favourable" and "unfavourable", so the number would be reporting its own noise. Above
#: it the return flattens hard: 30 to 50 buys 1.0 point of agreement and costs half the
#: table.
#:
#: Corroboration worth recording: Riftools' own ``confidence`` field, which we do not
#: read, switches from "Low" to "Medium" at exactly 30. Two methods, one boundary.
MIN_MATCHES = 30

#: Distinct events a cell needs. A matchup that happened at one tournament describes
#: that tournament, however many matches it holds.
#:
#: The same value ``performance.py`` uses, and on this data it is very nearly redundant
#: with :data:`MIN_MATCHES` -- worth recording so nobody mistakes it for load-bearing.
#: Of the 416 cells clearing the match floor, the *fewest* events any of them was seen at
#: is 6 and the median is 14, so this withholds 14 cells rather than the hundreds it
#: would if pairings were as concentrated as they intuitively seem.
#:
#: It stays because near-redundant is not redundant, and because the property it defends
#: is one of the table's window rather than its size: a set window with fewer, larger
#: events would pull those numbers down without changing a single match count.
MIN_EVENTS = 8

#: Reasons a rate is withheld, in the order they are checked. Reported, never silent.
WITHHELD_MATCHES = "matches"
WITHHELD_EVENTS = "events"


@dataclass(frozen=True)
class Matchup:
    """One legend's record against one opponent."""

    legend_id: str
    opponent_id: str
    legend_name: str
    opponent_name: str
    matches: int
    wins: int
    losses: int
    games_won: int
    games_lost: int
    #: Distinct events this pairing was seen at. Zero when the source shipped no
    #: per-event breakdown, which is treated as unknown rather than as none.
    events: int
    win_rate: float
    interval_low: float
    interval_high: float
    shown: bool
    withheld: str = ""

    @property
    def decisive(self) -> int:
        """Matches with a winner. This source records no draws, so it is every match."""
        return self.wins + self.losses

    @property
    def separated(self) -> bool:
        """True when the whole interval clears even -- the only safe "this is a edge"."""
        return self.shown and (self.interval_low > 0.5 or self.interval_high < 0.5)

    @property
    def favourable(self) -> bool:
        return self.separated and self.interval_low > 0.5

    @property
    def unfavourable(self) -> bool:
        return self.separated and self.interval_high < 0.5

    def describe(self) -> str:
        if not self.shown:
            return f"{self.matches} matches so far — {self.explain_withheld()}"
        return (
            f"{self.win_rate:.1%} over {self.decisive} matches "
            f"({self.interval_low:.1%}–{self.interval_high:.1%}"
            + (f", {self.events} events)" if self.events else ")")
        )

    def explain_withheld(self) -> str:
        if self.withheld == WITHHELD_MATCHES:
            return f"needs {MIN_MATCHES} matches to rate, has {self.decisive}"
        if self.withheld == WITHHELD_EVENTS:
            return f"needs {MIN_EVENTS} events to rate, has {self.events}"
        return "not enough evidence to rate"


@dataclass(frozen=True)
class LegendRecord:
    """One legend's overall record across the same events.

    Reported by the source rather than summed from the row above it, and the two do not
    reconcile exactly: the overall figure includes matches whose opponent's legend was
    never identified (516 players of 10,156 in the live table), which by definition
    cannot appear in any cell. Summing the row instead would quietly drop them and
    invent a second, different win rate for the same legend.
    """

    legend_id: str
    name: str
    matches: int
    wins: int
    losses: int
    games_won: int
    games_lost: int
    #: Distinct players who piloted it. A popularity signal, and the denominator behind
    #: any future pilot-concentration guard.
    players: int
    mirror_matches: int
    win_rate: float
    interval_low: float
    interval_high: float
    shown: bool
    withheld: str = ""

    @property
    def decisive(self) -> int:
        return self.wins + self.losses

    @property
    def separated(self) -> bool:
        return self.shown and (self.interval_low > 0.5 or self.interval_high < 0.5)

    def describe(self) -> str:
        if not self.shown:
            return f"{self.matches} matches so far — needs {MIN_MATCHES} to rate"
        return (
            f"{self.win_rate:.1%} over {self.decisive} matches "
            f"({self.interval_low:.1%}–{self.interval_high:.1%})"
        )


@dataclass(frozen=True)
class MatchupBasis:
    """What the table above is a table *of*.

    Rendered beside the numbers, not kept for a tooltip. These rates come from a source
    whose primary records we never see, over a window we did not choose, and a reader
    entitled to trust them is entitled to know that first.
    """

    #: What the upstream project calls its own source, verbatim.
    source_label: str
    #: The credit the data travels with.
    attribution: Mapping[str, str]
    #: e.g. ``"set4"``. The window the upstream table was built over -- **not** this
    #: project's ban era, which is derived separately and does not necessarily align.
    set_window: str
    published_at: str
    events: int
    #: Matches behind the matrix, and behind everything including mirrors.
    matrix_matches: int
    eligible_matches: int
    legends_measured: int
    legends_shown: int
    cells_measured: int
    cells_shown: int
    min_matches: int = MIN_MATCHES
    min_events: int = MIN_EVENTS

    def describe(self) -> str:
        return (
            f"{self.matrix_matches:,} recorded matches across {self.events} events "
            f"({self.set_window or 'current set'}), via {self.attribution.get('source', 'the source')}. "
            f"{self.cells_shown} of {self.cells_measured} matchups meet the "
            f"{self.min_matches}-match, {self.min_events}-event bar."
        )


@dataclass(frozen=True)
class MatchupTable:
    """Every matchup we hold, indexed for the two questions a client asks."""

    basis: MatchupBasis
    records: tuple[LegendRecord, ...] = ()
    matchups: tuple[Matchup, ...] = ()

    @property
    def available(self) -> bool:
        return bool(self.records)

    def record(self, legend_id: str) -> LegendRecord | None:
        return next((r for r in self.records if r.legend_id == legend_id), None)

    def ranked(self) -> tuple[LegendRecord, ...]:
        """Strongest first, then every unrated legend by sample size.

        Ordered by the interval's **lower bound**, for the reason
        ``performance.ranked`` gives: it is what stops a legend at 24-19 over 43 matches
        outranking one at 988-795 over 1,783. Ranking by the point estimate ranks the
        luckiest sample; ranking by the bound ranks the number we are most confident is
        true. On the live table those two orderings disagree in the top five.
        """
        return tuple(
            sorted(
                self.records,
                key=lambda r: (
                    not r.shown,
                    -r.interval_low if r.shown else 0,
                    -r.decisive,
                    r.name,
                ),
            )
        )

    def for_legend(self, legend_id: str) -> tuple[Matchup, ...]:
        """One legend's spread, hardest opponent first, then the unrated by sample.

        Hardest is ordered on the interval's **upper** bound -- the mirror of
        :meth:`ranked`, and the same argument: a matchup is confidently bad when even
        the optimistic end of its interval is low, not when a thin sample happened to
        come out badly.
        """
        rows = [m for m in self.matchups if m.legend_id == legend_id]
        return tuple(
            sorted(
                rows,
                key=lambda m: (
                    not m.shown,
                    m.interval_high if m.shown else 0,
                    -m.decisive,
                    m.opponent_name,
                ),
            )
        )

    def between(self, legend_id: str, opponent_id: str) -> Matchup | None:
        return next(
            (
                m
                for m in self.matchups
                if m.legend_id == legend_id and m.opponent_id == opponent_id
            ),
            None,
        )


# -- construction -------------------------------------------------------------


def _rate(wins: int, losses: int, events: int) -> tuple[float, float, float, bool, str]:
    decisive = wins + losses
    rate, low, high = wilson(wins, decisive)
    if decisive < MIN_MATCHES:
        return rate, low, high, False, WITHHELD_MATCHES
    # Zero events means the source shipped no per-event breakdown at all. That is
    # unknown, not "one event", and withholding the whole table on a missing optional
    # field would be the wrong way round.
    if events and events < MIN_EVENTS:
        return rate, low, high, False, WITHHELD_EVENTS
    return rate, low, high, True, ""


def build_matchups(
    *,
    cells: Iterable[Mapping[str, object]],
    legends: Iterable[Mapping[str, object]],
    catalog: Catalog,
    source_label: str = "",
    attribution: Mapping[str, str] | None = None,
    set_window: str = "",
    published_at: str = "",
    events: int = 0,
    matrix_matches: int = 0,
    eligible_matches: int = 0,
) -> tuple[MatchupTable, list[str]]:
    """Resolve names to card ids and apply the publication bar.

    Returns the table and any notes worth surfacing -- unresolved legend names most of
    all. A name we cannot resolve is dropped from the table and *named* in the notes: a
    silently missing row looks identical to a legend nobody played, and the two want
    opposite responses from whoever reads the log.
    """
    notes: list[str] = []
    unresolved: set[str] = set()

    def resolve(name: str) -> tuple[str, str]:
        """``(card_id, display_name)``, or ``("", name)`` when the catalogue has no match."""
        card = catalog.resolve(name) if name else None
        if card is None:
            if name:
                unresolved.add(name)
            return "", name
        return card.card_id, card.name

    records: list[LegendRecord] = []
    for row in legends:
        name = str(row.get("legend") or "")
        legend_id, display = resolve(name)
        if not legend_id:
            continue
        wins, losses = int(row.get("wins") or 0), int(row.get("losses") or 0)
        rate, low, high, shown, withheld = _rate(wins, losses, events=0)
        records.append(
            LegendRecord(
                legend_id=legend_id,
                name=display,
                matches=int(row.get("matches") or 0),
                wins=wins,
                losses=losses,
                games_won=int(row.get("gamesWon") or 0),
                games_lost=int(row.get("gamesLost") or 0),
                players=int(row.get("players") or 0),
                mirror_matches=int(row.get("mirrorMatches") or 0),
                win_rate=rate,
                interval_low=low,
                interval_high=high,
                shown=shown,
                withheld=withheld,
            )
        )

    rows: list[Matchup] = []
    for cell in cells:
        legend_id, legend_name = resolve(str(cell.get("legend") or ""))
        opponent_id, opponent_name = resolve(str(cell.get("opponent") or ""))
        if not legend_id or not opponent_id:
            continue
        wins, losses = int(cell.get("wins") or 0), int(cell.get("losses") or 0)
        cell_events = int(cell.get("events") or 0)
        rate, low, high, shown, withheld = _rate(wins, losses, cell_events)
        rows.append(
            Matchup(
                legend_id=legend_id,
                opponent_id=opponent_id,
                legend_name=legend_name,
                opponent_name=opponent_name,
                matches=int(cell.get("matches") or 0),
                wins=wins,
                losses=losses,
                games_won=int(cell.get("gamesWon") or 0),
                games_lost=int(cell.get("gamesLost") or 0),
                events=cell_events,
                win_rate=rate,
                interval_low=low,
                interval_high=high,
                shown=shown,
                withheld=withheld,
            )
        )

    if unresolved:
        listed = ", ".join(sorted(unresolved)[:5])
        more = f" (+{len(unresolved) - 5} more)" if len(unresolved) > 5 else ""
        notes.append(f"{len(unresolved)} legend name(s) did not resolve: {listed}{more}")

    basis = MatchupBasis(
        source_label=source_label,
        attribution=dict(attribution or {}),
        set_window=set_window,
        published_at=published_at,
        events=events,
        matrix_matches=matrix_matches,
        eligible_matches=eligible_matches,
        legends_measured=len(records),
        legends_shown=sum(1 for r in records if r.shown),
        cells_measured=len(rows),
        cells_shown=sum(1 for m in rows if m.shown),
    )
    return MatchupTable(basis=basis, records=tuple(records), matchups=tuple(rows)), notes


# -- integrity ----------------------------------------------------------------


def symmetry_errors(cells: Sequence[Mapping[str, object]], *, limit: int = 5) -> list[str]:
    """Check that every cell mirrors its opposite, and report the ones that do not.

    A matchup matrix describes each match twice -- once from each side -- so A's wins
    over B must equal B's losses to A. On the live table this holds for all 1,740 cells,
    which is the strongest signal available that the aggregate means what we think it
    means.

    It is checked rather than assumed because this is data we cannot audit any other
    way. If the upstream ever changes what a cell counts -- games instead of matches,
    say, or a filtered population on one axis -- symmetry is the first thing that breaks,
    and it breaks loudly here instead of quietly becoming a wrong number on a page.
    """
    index = {
        (str(c.get("legend") or ""), str(c.get("opponent") or "")): c for c in cells
    }
    problems: list[str] = []
    for (legend, opponent), cell in index.items():
        back = index.get((opponent, legend))
        if back is None:
            problems.append(f"{legend} vs {opponent} has no opposing cell")
        elif int(cell.get("wins") or 0) != int(back.get("losses") or 0) or int(
            cell.get("losses") or 0
        ) != int(back.get("wins") or 0):
            problems.append(
                f"{legend} vs {opponent} does not mirror: "
                f"{cell.get('wins')}-{cell.get('losses')} against "
                f"{back.get('wins')}-{back.get('losses')}"
            )
        if len(problems) >= limit:
            problems.append("…")
            break
    return problems
