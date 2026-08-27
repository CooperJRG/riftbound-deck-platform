"""What is actually winning, as opposed to what is being played.

Every other module in this package measures *presence* — how much of the published
field a deck occupies. Presence is not performance, and until now the product had no
way to say so: the tier wall ranks legends on ``share x 0.58 + events x 0.27 +
movement x 0.15``, and the product plan states plainly that the page does not claim a
win rate. That was the right call while there was no win rate to claim.

There is one. Every TopDeck standing carries the player's match record, and 3,491 of
them join to a published list — 20,783 matches, 13,322 of them in the current ban era.
The field was being formatted into a display string at ingest and never read back.

The two orderings are only moderately alike (Kendall tau of +0.587 across the archetypes
with enough matches to rank), and where they disagree they disagree about things a
player would want to know: the most-played deck in the format is the eighth-best
performing, and the second-best performing deck sits in B tier on presence alone.

Three disciplines carry over from the rest of the package, and one is new.

**Honest denominators.** Draws are neither wins nor losses, so the win rate divides by
decisive matches while the sample size reports every match played. Both numbers travel
together.

**A confidence interval, not a point.** A rate without a sample size invites a reader to
rank 5-1 above 61-39. Wilson rather than normal-approximation because it stays sane at
the small counts most archetypes actually have.

**Refusal.** Below :data:`MIN_MATCHES` the number churns — split-half resampling puts
the mean absolute disagreement between two halves of the event set at 8.4 points at a
30-match floor, against 3.8 at the threshold actually shipped. An archetype under the
bar gets an explicit "not enough matches yet", never a rate in small type. **18 of 92
archetypes clear it.** That is the honest size of this feature, and it is reported in
the response rather than left for a reader to infer from a short list.

**Published lists are not the field.** Standings whose list was published win 50.7% of
their matches; those without win 46.3%. The gap is mostly players who dropped, and it
is why every rate here is labelled as a rate *among published lists*.
:class:`PerformanceBasis` carries the gap in the response so the caveat is data rather
than a footnote somebody can forget to render.

Deliberately not a model. A latent-strength fit (Bradley-Terry, Elo) is the obvious
next idea and it was measured and rejected: strength of schedule across the qualifying
archetypes spans 2.04 points while their win rates span 28.5, so the correction it
exists to make is smaller than the noise floor — and with no opponent recorded on any
row, such a fit reconstructs its answer from the marginals, which *are* the win rate.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from ..cards import Catalog
from ..eras import Era, Eras
from ..meta import MetaDeck, Standing, Tournament
from .common import (
    Dimension,
    TrendFilter,
    _eligible_decks,
    _entity_id,
    _entity_name,
    _tournaments_in_scope,
    parse_date,
)

#: Decisive matches an entity needs before a win rate is published.
#:
#: Set from split-half stability rather than taste. Rank the archetypes on a random half
#: of the events, again on the other half, and compare — 400 resamples per floor,
#: averaged over six seeds, against the live snapshot:
#:
#:   floor     100     150     200     250     300     400     500
#:   tau    +0.460  +0.522  +0.534  +0.523  +0.499  +0.378  +0.306
#:   error   4.40%   3.94%   3.76%   3.60%   3.46%   3.18%   2.92%
#:   shown      25      19      18      17      14       9       7
#:
#: Two things fall out of that table, and the second was a surprise worth recording.
#:
#: Per-rate precision improves monotonically with the floor — of course it does, the
#: samples get bigger. But **rank agreement peaks at 200 and then collapses**. Above
#: roughly 300 the survivors are so few, and so tightly bunched around the mean, that
#: ordering them is mostly ordering noise: at a 500-match floor seven archetypes remain
#: and tau falls to +0.306, worse than at 100. A higher bar is not a safer number.
#:
#: 200 is the peak on rank stability and within 0.2 points of the best error, at the
#: cost of one entity against a floor of 150.
MIN_MATCHES = 200

#: Distinct events an entity needs. A rate earned at one tournament describes that
#: tournament, however many matches it contains.
MIN_EVENTS = 8

#: Share of an entity's matches one pilot may account for before the rate is withheld.
#: Above this the number is a player rating wearing a deck's name. The worst offender in
#: the live snapshot sits at 15.0%, so this bites rarely — which is the point of having
#: it before it is needed rather than after.
MAX_PILOT_SHARE = 0.20

#: Reasons a rate is withheld, in the order they are checked. Reported, never silent.
WITHHELD_MATCHES = "matches"
WITHHELD_EVENTS = "events"
WITHHELD_PILOT = "pilot-concentration"


def wilson(wins: int, decisive: int, *, z: float = 1.96) -> tuple[float, float, float]:
    """``(rate, low, high)`` for a binomial proportion, at 95% by default.

    Wilson rather than ``p +/- z*sqrt(p(1-p)/n)``: the normal approximation produces
    bounds outside [0, 1] at the sample sizes most archetypes have, and a interval that
    says a deck wins 103% of its games discredits every other number on the page.
    """
    if decisive <= 0:
        return (0.0, 0.0, 1.0)
    rate = wins / decisive
    denominator = 1.0 + z * z / decisive
    centre = (rate + z * z / (2 * decisive)) / denominator
    spread = z * math.sqrt(rate * (1 - rate) / decisive + z * z / (4 * decisive * decisive))
    spread /= denominator
    return (rate, max(0.0, centre - spread), min(1.0, centre + spread))


@dataclass(frozen=True)
class Performance:
    """How one entity fared, and whether we are willing to say so."""
    entity_id: str
    name: str
    #: Lists that carried a match record. Lower than the entity's deck count, because
    #: not every published list has a standing behind it.
    decks_with_records: int
    matches: int          # every match played, draws included
    decisive: int         # matches with a winner: the win-rate denominator
    wins: int
    losses: int
    draws: int
    events: int
    pilots: int
    top_pilot_share: float
    win_rate: float
    interval_low: float
    interval_high: float
    #: False when the sample cannot support a published rate. The counts stay populated
    #: either way, so a client can show "62 matches so far" instead of a blank.
    shown: bool
    withheld: str = ""

    @property
    def separated(self) -> bool:
        """True when the whole interval sits above even. The only safe "this wins"."""
        return self.shown and self.interval_low > 0.5

    def describe(self) -> str:
        if not self.shown:
            return f"{self.matches} matches so far — {self.explain_withheld()}"
        return (
            f"{self.win_rate:.1%} over {self.decisive} decisive matches "
            f"({self.interval_low:.1%}–{self.interval_high:.1%}, {self.events} events)"
        )

    @property
    def withheld_reason(self) -> str:
        """Which threshold was missed, as a stable token a client can branch on."""
        return self.withheld

    @property
    def withheld_detail(self) -> str:
        """The same thing in plain English. Empty when the rate is shown.

        Rendered rather than reimplemented: a client that had to know the thresholds to
        explain them is a second copy of the policy, and only one copy is tested.
        """
        return "" if self.shown else self.explain_withheld()

    def explain_withheld(self) -> str:
        """Why no rate is shown, in words a player can act on."""
        if self.withheld == WITHHELD_MATCHES:
            return f"needs {MIN_MATCHES} decisive matches to rank, has {self.decisive}"
        if self.withheld == WITHHELD_EVENTS:
            return f"needs {MIN_EVENTS} events to rank, has {self.events}"
        if self.withheld == WITHHELD_PILOT:
            return (
                f"one player accounts for {self.top_pilot_share:.0%} of these matches, "
                f"so this would rate the pilot rather than the deck"
            )
        return "not enough evidence to rank"


@dataclass(frozen=True)
class PerformanceBasis:
    """What the rates above are a rate *of*, so nobody has to guess.

    Rendered beside the column rather than kept for a tooltip: the difference between
    "this deck wins 62% of its games" and "this deck wins 62% of the games we can see"
    is the whole honesty of the feature.
    """
    era_id: str
    era_name: str
    era_from: str
    era_to: str
    #: True when the era boundary cites a published announcement rather than being
    #: derived from the archive. Currently false, and it should stay visible until it
    #: is not.
    era_cited: bool
    era_evidence: str
    entities_measured: int
    entities_shown: int
    entities_withheld: int
    decks_with_records: int
    total_matches: int
    #: Win rate of standings whose list *was* published, and of those whose was not.
    #: The gap is the selection bias in one number; comparisons between entities inside
    #: the published population survive it, claims about "the field" do not.
    published_win_rate: float
    unpublished_win_rate: float
    published_standings: int
    unpublished_standings: int

    @property
    def publication_gap(self) -> float:
        return self.published_win_rate - self.unpublished_win_rate

    def describe(self) -> str:
        return (
            f"{self.total_matches:,} matches from {self.decks_with_records:,} published "
            f"lists in {self.era_name}. {self.entities_shown} ranked, "
            f"{self.entities_withheld} short of the sample needed."
        )

    @property
    def caveat(self) -> str:
        """The sentence that has to appear wherever a rate does."""
        return (
            f"Win rate among published lists only. Lists that were published win "
            f"{self.publication_gap:+.1%} more than those that were not, mostly players "
            f"who dropped, so these rank decks against each other rather than against "
            f"the whole field."
        )


@dataclass(frozen=True)
class PerformanceTable:
    """Every entity's performance for one window, plus what it is a measure of."""
    basis: PerformanceBasis
    rows: Mapping[str, Performance] = field(default_factory=dict)

    def get(self, entity_id: str) -> Performance | None:
        return self.rows.get(entity_id)

    def ranked(self) -> tuple[Performance, ...]:
        """Publishable rows, strongest first.

        Ordered by the interval's **lower bound**, not the point estimate. That is what
        stops a 4-1 archetype outranking one that is 340-260: ranking by the number we
        are most confident is true, rather than by the luckiest sample.
        """
        shown = [row for row in self.rows.values() if row.shown]
        shown.sort(key=lambda row: (-row.interval_low, -row.decisive, row.name))
        return tuple(shown)


def _standings_in_scope(
    standings: Iterable[Standing],
    tournaments: Mapping[str, Tournament],
    era: Era,
) -> list[Standing]:
    """Standings from events inside the window *and* inside the era."""
    out: list[Standing] = []
    for standing in standings:
        tournament = tournaments.get(standing.tournament_slug)
        if tournament is None or parse_date(tournament.date) is None:
            continue
        if era.era_id != "all" and not era.contains(tournament.date):
            continue
        out.append(standing)
    return out


def _publication_bias(
    standings: Iterable[Standing], published_slugs: set[str]
) -> tuple[float, float, int, int]:
    """Win rates of the published and unpublished halves of the same events.

    The single most important honesty check in the module, and cheap: it is the same
    pass over the same rows, split on whether a list came with the record.
    """
    pub_w = pub_n = unpub_w = unpub_n = 0
    pub_rows = unpub_rows = 0
    for standing in standings:
        wins, losses, _draws = standing.match_record
        decisive = wins + losses
        if decisive <= 0:
            continue
        if standing.deck_slug in published_slugs:
            pub_w += wins
            pub_n += decisive
            pub_rows += 1
        else:
            unpub_w += wins
            unpub_n += decisive
            unpub_rows += 1
    return (
        pub_w / pub_n if pub_n else 0.0,
        unpub_w / unpub_n if unpub_n else 0.0,
        pub_rows,
        unpub_rows,
    )


def performance(
    *,
    decks: Iterable[MetaDeck],
    tournaments: Iterable[Tournament],
    standings: Iterable[Standing],
    catalog: Catalog,
    trend_filter: TrendFilter,
    eras: Eras,
    era_id: str = "",
    dimension: Dimension = "archetype",
) -> PerformanceTable:
    """Aggregate match records by entity for one window and one era.

    Pure and cheap — one pass over the standings, 6 ms over the whole live snapshot —
    so it can sit in the same precompute as the rest of the trend aggregation rather
    than needing an artifact of its own.
    """
    era = eras.resolve(era_id)
    all_tournaments = list(tournaments)
    scoped = _tournaments_in_scope(all_tournaments, trend_filter)
    if era.era_id != "all":
        scoped = [row for row in scoped if era.contains(row.date)]
    tournament_map = {row.slug: row for row in scoped}

    eligible = _eligible_decks(decks, tournament_map)
    deck_by_id = {deck.deck_id: deck for deck in eligible}

    in_scope = _standings_in_scope(standings, tournament_map, era)
    published_rate, unpublished_rate, published_rows, unpublished_rows = _publication_bias(
        in_scope, set(deck_by_id)
    )

    wins: dict[str, int] = defaultdict(int)
    losses: dict[str, int] = defaultdict(int)
    draws: dict[str, int] = defaultdict(int)
    lists: dict[str, int] = defaultdict(int)
    events: dict[str, set[str]] = defaultdict(set)
    pilots: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    names: dict[str, str] = {}

    for standing in in_scope:
        deck = deck_by_id.get(standing.deck_slug)
        if deck is None:
            continue
        entity_id = _entity_id(deck, dimension)
        if not entity_id:
            continue
        won, lost, drawn = standing.match_record
        if won + lost + drawn <= 0:
            continue  # a standing with no record is not evidence of a 0% win rate
        wins[entity_id] += won
        losses[entity_id] += lost
        draws[entity_id] += drawn
        lists[entity_id] += 1
        events[entity_id].add(standing.tournament_slug)
        # An unnamed player cannot be told apart from another unnamed player, so they
        # are counted as one pilot -- the pessimistic reading, which is the safe one for
        # a check whose job is to catch concentration.
        pilots[entity_id][standing.player_name or "unknown"] += won + lost + drawn
        names.setdefault(entity_id, _entity_name(deck, dimension, catalog))

    rows: dict[str, Performance] = {}
    for entity_id in wins.keys() | losses.keys() | draws.keys():
        won, lost, drawn = wins[entity_id], losses[entity_id], draws[entity_id]
        matches = won + lost + drawn
        decisive = won + lost
        event_count = len(events[entity_id])
        pilot_counts = pilots[entity_id]
        top_share = (max(pilot_counts.values()) / matches) if matches and pilot_counts else 0.0

        withheld = ""
        if decisive < MIN_MATCHES:
            withheld = WITHHELD_MATCHES
        elif event_count < MIN_EVENTS:
            withheld = WITHHELD_EVENTS
        elif top_share > MAX_PILOT_SHARE:
            withheld = WITHHELD_PILOT

        rate, low, high = wilson(won, decisive)
        rows[entity_id] = Performance(
            entity_id=entity_id,
            name=names.get(entity_id, entity_id),
            decks_with_records=lists[entity_id],
            matches=matches,
            decisive=decisive,
            wins=won,
            losses=lost,
            draws=drawn,
            events=event_count,
            pilots=len(pilot_counts),
            top_pilot_share=top_share,
            win_rate=rate,
            interval_low=low,
            interval_high=high,
            shown=not withheld,
            withheld=withheld,
        )

    shown = sum(1 for row in rows.values() if row.shown)
    basis = PerformanceBasis(
        era_id=era.era_id,
        era_name=era.name,
        era_from=era.from_date,
        era_to=era.to_date,
        era_cited=era.is_cited,
        era_evidence=era.evidence,
        entities_measured=len(rows),
        entities_shown=shown,
        entities_withheld=len(rows) - shown,
        decks_with_records=sum(lists.values()),
        total_matches=sum(row.matches for row in rows.values()),
        published_win_rate=published_rate,
        unpublished_win_rate=unpublished_rate,
        published_standings=published_rows,
        unpublished_standings=unpublished_rows,
    )
    return PerformanceTable(basis=basis, rows=rows)


def signal_to_noise(table: PerformanceTable) -> float:
    """How much of the spread between entities is real rather than sampling noise.

    Observed variance of the published rates divided by the variance binomial sampling
    alone would produce at these sample sizes. Above 1 means entities genuinely differ;
    at 1 the ranking is a ranking of coin flips.

    This is the kill switch. v2 shipped a recommender that returned nothing four times
    in five and nobody noticed, because nothing measured the thing that would have been
    embarrassing. If this ratio ever falls to 1 the column should withhold itself rather
    than print an ordering of noise — so it is computed, asserted on, and reported.
    """
    rows = [row for row in table.rows.values() if row.shown and row.decisive > 0]
    if len(rows) < 2:
        return 0.0
    mean = sum(row.win_rate for row in rows) / len(rows)
    observed = sum((row.win_rate - mean) ** 2 for row in rows) / len(rows)
    expected = sum(
        row.win_rate * (1 - row.win_rate) / row.decisive for row in rows
    ) / len(rows)
    if expected <= 0:
        return 0.0
    return observed / expected
