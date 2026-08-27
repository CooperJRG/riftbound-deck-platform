"""Is the win rate a number, or is it noise wearing a decimal point?

An acceptance criterion that isn't measured is a hope. This is the win-rate column's
equivalent of :mod:`smart_decks_harness` — the checks that have to pass before a rate
is allowed on a screen, written so the embarrassing ones are the ones on the dashboard.

Six numbers, and the reason each exists:

===========================  ===================================================
metric                       what it catches
===========================  ===================================================
``split_half_tau``           A ranking that does not survive resampling. Rank the
                             entities on a random half of the events, again on the
                             other half, and compare. This is the metric that set
                             :data:`~meta_trends.performance.MIN_MATCHES`.
``split_half_error``         How many points a reader should expect the number to
                             move between snapshots, for no real reason.
``signal_to_noise``          Whether entities differ by more than binomial chance
                             would produce anyway. **The kill switch.**
``max_pilot_share``          One hot player becoming a deck rating.
``publication_gap``          The selection bias, reported every run. Not bounded —
                             it is a property of the source, not a defect — but a
                             sharp move in it means the source changed under us.
``withheld``                 How much of the field we cannot rank. Published
                             because it is the number that makes the feature look
                             small, and it is true.
===========================  ===================================================

The reference point, as ever: v2 shipped a recommender whose own evaluation recorded
``strictBuildableEmptyResultRate: 0.814`` and nobody noticed, because the metric that
would have embarrassed it was computed and then not put in front of anyone.
"""

from __future__ import annotations

import itertools
import random
import statistics
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from .cards import Catalog
from .eras import Eras
from .meta import MetaDeck, Standing, Tournament
from .meta_trends.common import TrendFilter, _eligible_decks, _entity_id, _tournaments_in_scope
from .meta_trends.performance import (
    MAX_PILOT_SHARE,
    MIN_EVENTS,
    MIN_MATCHES,
    PerformanceTable,
    performance,
    signal_to_noise,
)

#: Split-half rank agreement the shipping threshold has to clear.
#:
#: Measured at :data:`~meta_trends.performance.MIN_MATCHES` on the live snapshot:
#: **+0.534**, with a worst-seed value of +0.524.
#:
#: Set at 0.45 rather than at the measured value, for a reason worth writing down: the
#: first cut of this gate targeted 0.50 against a measurement of ~0.51, and it passed or
#: failed **depending on the random seed** — +0.498 on one, +0.522 on another. A gate
#: that flips on its own seed is worse than no gate, because it teaches whoever hits it
#: to re-run until it goes green. The fix was both halves: enough resamples that the
#: estimate is reproducible (see :data:`SPLIT_HALF_TRIALS`), and a threshold with real
#: margin under it so ordinary drift does not trip it while a collapse still does.
TARGET_SPLIT_HALF_TAU = 0.45

#: Points of disagreement between two halves of the event set, at the shipping
#: threshold. Bounds the churn a reader should expect between snapshots. Measured: 3.76%.
TARGET_SPLIT_HALF_ERROR = 0.05

#: Ratio of observed between-entity variance to the variance sampling alone would
#: produce. At 1.0 the ranking is a ranking of coin flips. Measured: 4.39x.
TARGET_SIGNAL_TO_NOISE = 2.0

#: Resamples used for the split-half estimate.
#:
#: Chosen for reproducibility, not for the mean — the mean barely moves. Spread of the
#: estimate across twelve seeds: 0.045 at 40 trials, 0.032 at 100, 0.025 at 200,
#: **0.016 at 400**. At 40 the seed moved the answer by more than the margin the gate
#: was being asked to judge. 400 costs 0.13s in a command that is never imported by a
#: test.
SPLIT_HALF_TRIALS = 400


@dataclass(frozen=True)
class Report:
    """One acceptance run."""
    era_name: str
    dimension: str
    entities_measured: int
    entities_shown: int
    entities_withheld: int
    total_matches: int
    decks_with_records: int
    split_half_tau: float
    split_half_error: float
    split_half_entities: float
    signal_to_noise: float
    max_pilot_share: float
    publication_gap: float
    published_win_rate: float
    unpublished_win_rate: float

    @property
    def failures(self) -> tuple[str, ...]:
        """Every target missed, named. Empty when the run passes."""
        out: list[str] = []
        if self.entities_shown < 1:
            out.append("no entity clears the sample threshold — nothing to publish")
        if self.split_half_tau < TARGET_SPLIT_HALF_TAU:
            out.append(
                f"split-half tau {self.split_half_tau:+.3f} below "
                f"{TARGET_SPLIT_HALF_TAU:+.2f} — the ranking does not survive resampling"
            )
        if self.split_half_error > TARGET_SPLIT_HALF_ERROR:
            out.append(
                f"split-half error {self.split_half_error:.1%} above "
                f"{TARGET_SPLIT_HALF_ERROR:.0%} — the column would churn between snapshots"
            )
        if self.signal_to_noise < TARGET_SIGNAL_TO_NOISE:
            out.append(
                f"signal-to-noise {self.signal_to_noise:.2f}x below "
                f"{TARGET_SIGNAL_TO_NOISE:.1f}x — entities differ by no more than chance"
            )
        if self.max_pilot_share > MAX_PILOT_SHARE:
            out.append(
                f"one pilot holds {self.max_pilot_share:.0%} of a published entity's "
                f"matches, above {MAX_PILOT_SHARE:.0%}"
            )
        return tuple(out)

    @property
    def passes(self) -> bool:
        return not self.failures

    def render(self) -> str:
        lines = [
            f"era                     {self.era_name}",
            f"dimension               {self.dimension}",
            f"matches                 {self.total_matches:,} "
            f"from {self.decks_with_records:,} published lists",
            f"entities ranked         {self.entities_shown} of {self.entities_measured}"
            f"   ({self.entities_withheld} short of the sample needed)",
            f"split-half tau          {self.split_half_tau:+.3f}"
            f"   (target >= {TARGET_SPLIT_HALF_TAU:+.2f})",
            f"split-half error        {self.split_half_error:.1%}"
            f"     (target <= {TARGET_SPLIT_HALF_ERROR:.0%})",
            f"  entities compared     {self.split_half_entities:.0f} per resample",
            f"signal-to-noise         {self.signal_to_noise:.2f}x"
            f"    (target >= {TARGET_SIGNAL_TO_NOISE:.1f}x)",
            f"max pilot share         {self.max_pilot_share:.1%}"
            f"    (target <= {MAX_PILOT_SHARE:.0%})",
            f"publication gap         {self.publication_gap:+.1%}"
            f"    (reported, not bounded: {self.published_win_rate:.1%} published "
            f"vs {self.unpublished_win_rate:.1%} not)",
            f"thresholds              {MIN_MATCHES} decisive matches, {MIN_EVENTS} events",
        ]
        return "\n".join(lines)


def _kendall_tau(left: Mapping[str, float], right: Mapping[str, float]) -> tuple[float, int]:
    """Rank agreement between two scorings of the same entities."""
    shared = sorted(set(left) & set(right))
    concordant = discordant = 0
    for a, b in itertools.combinations(shared, 2):
        first = left[a] - left[b]
        second = right[a] - right[b]
        if first * second > 0:
            concordant += 1
        elif first * second < 0:
            discordant += 1
    total = concordant + discordant
    return ((concordant - discordant) / total if total else 0.0, len(shared))


def _rates_over(
    events: set[str],
    observations: Sequence[tuple[str, str, int, int]],
    *,
    minimum: int,
) -> dict[str, float]:
    """Win rate per entity over a subset of events, above a match floor."""
    wins: dict[str, int] = {}
    decisive: dict[str, int] = {}
    for slug, entity_id, won, lost in observations:
        if slug not in events:
            continue
        wins[entity_id] = wins.get(entity_id, 0) + won
        decisive[entity_id] = decisive.get(entity_id, 0) + won + lost
    return {
        entity_id: wins[entity_id] / decisive[entity_id]
        for entity_id in decisive
        if decisive[entity_id] >= minimum
    }


def split_half(
    observations: Sequence[tuple[str, str, int, int]],
    *,
    minimum: int,
    trials: int = SPLIT_HALF_TRIALS,
    rng: random.Random | None = None,
) -> tuple[float, float, float]:
    """``(mean tau, mean absolute rate difference, mean entities compared)``.

    Splits on **events**, not on individual standings. Splitting on standings would
    leave the same tournament on both sides and flatter the result — two halves of one
    event are far more alike than two different events, which is precisely the
    correlation the metric is meant to expose.

    Each half sees roughly half the matches, so the per-half floor is ``minimum / 2``:
    the question is whether a rate computed the way we ship it reproduces, not whether
    half a sample reproduces a full one.
    """
    generator = rng or random.Random(20260826)
    events = sorted({slug for slug, _entity, _won, _lost in observations})
    if len(events) < 4:
        return (0.0, 0.0, 0.0)

    taus: list[float] = []
    errors: list[float] = []
    counts: list[int] = []
    half_floor = max(1, minimum // 2)
    for _ in range(max(1, trials)):
        shuffled = events[:]
        generator.shuffle(shuffled)
        cut = len(shuffled) // 2
        left = _rates_over(set(shuffled[:cut]), observations, minimum=half_floor)
        right = _rates_over(set(shuffled[cut:]), observations, minimum=half_floor)
        shared = set(left) & set(right)
        if len(shared) < 5:
            continue
        tau, count = _kendall_tau(left, right)
        taus.append(tau)
        counts.append(count)
        errors.append(statistics.mean(abs(left[k] - right[k]) for k in shared))
    if not taus:
        return (0.0, 0.0, 0.0)
    return (statistics.mean(taus), statistics.mean(errors), statistics.mean(counts))


def observations(
    *,
    decks: Iterable[MetaDeck],
    tournaments: Iterable[Tournament],
    standings: Iterable[Standing],
    trend_filter: TrendFilter,
    eras: Eras,
    era_id: str = "",
    dimension: str = "archetype",
) -> list[tuple[str, str, int, int]]:
    """``(event slug, entity id, wins, losses)`` for every list with a record.

    The same join :func:`~meta_trends.performance.performance` makes, kept separate so
    the harness resamples the underlying evidence rather than re-deriving conclusions
    from an aggregate it cannot take apart again.
    """
    era = eras.resolve(era_id)
    scoped = _tournaments_in_scope(list(tournaments), trend_filter)
    if era.era_id != "all":
        scoped = [row for row in scoped if era.contains(row.date)]
    tournament_map = {row.slug: row for row in scoped}
    deck_by_id = {deck.deck_id: deck for deck in _eligible_decks(decks, tournament_map)}

    out: list[tuple[str, str, int, int]] = []
    for standing in standings:
        if standing.tournament_slug not in tournament_map:
            continue
        deck = deck_by_id.get(standing.deck_slug)
        if deck is None:
            continue
        entity_id = _entity_id(deck, dimension)  # type: ignore[arg-type]
        if not entity_id:
            continue
        won, lost, _drawn = standing.match_record
        if won + lost <= 0:
            continue
        out.append((standing.tournament_slug, entity_id, won, lost))
    return out


def evaluate(
    *,
    decks: Sequence[MetaDeck],
    tournaments: Sequence[Tournament],
    standings: Sequence[Standing],
    catalog: Catalog,
    trend_filter: TrendFilter,
    eras: Eras,
    era_id: str = "",
    dimension: str = "archetype",
    trials: int = SPLIT_HALF_TRIALS,
    rng: random.Random | None = None,
) -> tuple[Report, PerformanceTable]:
    """Run every acceptance check against one window. Returns the report and the table."""
    table = performance(
        decks=decks,
        tournaments=tournaments,
        standings=standings,
        catalog=catalog,
        trend_filter=trend_filter,
        eras=eras,
        era_id=era_id,
        dimension=dimension,  # type: ignore[arg-type]
    )
    rows = observations(
        decks=decks,
        tournaments=tournaments,
        standings=standings,
        trend_filter=trend_filter,
        eras=eras,
        era_id=era_id,
        dimension=dimension,
    )
    tau, error, compared = split_half(rows, minimum=MIN_MATCHES, trials=trials, rng=rng)
    published = table.ranked()
    basis = table.basis
    return (
        Report(
            era_name=basis.era_name,
            dimension=dimension,
            entities_measured=basis.entities_measured,
            entities_shown=basis.entities_shown,
            entities_withheld=basis.entities_withheld,
            total_matches=basis.total_matches,
            decks_with_records=basis.decks_with_records,
            split_half_tau=tau,
            split_half_error=error,
            split_half_entities=compared,
            signal_to_noise=signal_to_noise(table),
            max_pilot_share=max((row.top_pilot_share for row in published), default=0.0),
            publication_gap=basis.publication_gap,
            published_win_rate=basis.published_win_rate,
            unpublished_win_rate=basis.unpublished_win_rate,
        ),
        table,
    )
