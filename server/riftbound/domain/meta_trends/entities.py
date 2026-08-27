"""Share of the field, by champion, legend or archetype.

A *share* here is a partition: every charted list has exactly one champion, so the
shares sum to 1. That is what separates this module from `cards`, where they do not.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import replace

from ..cards import Catalog
from ..eras import Eras
from ..meta import MetaDeck, Standing, Tournament
from .common import (
    MIN_DECKS_FOR_CHART_POINT,
    MIN_DECKS_FOR_MOMENTUM,
    Dimension,
    EntityTrend,
    TrendFilter,
    TrendOverview,
    TrendPoint,
    _confidence,
    _coverage,
    _eligible_decks,
    _entity_id,
    _entity_name,
    _period,
    _periods,
    _tournaments_in_scope,
    archive_span,
    parse_date,
)
from .performance import PerformanceTable
from .performance import performance as performance_table
from .ranking import TIER_LAST, Candidate, Rank, rank_entities

#: Limit for the internal archive pass. The public route caps `limit` at 50; this call
#: is ours and must see the whole field, or an entity would look dormant purely because
#: it fell off the end of a truncated list.
_UNLIMITED = 1_000_000


def _apply_ranking(series: Sequence[EntityTrend]) -> list[EntityTrend]:
    """Score the field 0-100, assign tiers, and return it in rank order.

    Done here rather than in the client, where it used to live: it is the last piece of
    ranking policy that was outside the server, it was the only one with no tests, and
    the dormant entities it now has to order can only be found from data the client
    never asked for.
    """
    ranks = rank_entities(
        [
            Candidate(
                entity_id=row.entity_id,
                name=row.name,
                share=row.share,
                event_count=row.event_count,
                momentum=row.momentum,
                ranked=row.deck_count > 0,
                prior_share=row.rank.prior_share if row.rank else 0.0,
                prior_momentum=row.rank.prior_momentum if row.rank else None,
                last_seen=row.rank.last_seen if row.rank else "",
            )
            for row in series
        ]
    )
    ordered = sorted(series, key=lambda row: ranks[row.entity_id].position)
    return [replace(row, rank=ranks[row.entity_id]) for row in ordered]


def _dormant_series(
    *,
    decks: Iterable[MetaDeck],
    tournaments: Sequence[Tournament],
    standing_count_by_tournament: Mapping[str, int],
    catalog: Catalog,
    trend_filter: TrendFilter,
    dimension: Dimension,
    present: set[str],
) -> list[EntityTrend]:
    """Entities the archive knows but this window does not.

    Computed by running the same aggregation over the archive span -- reuse rather than
    a second implementation, because a separate one is how two numbers for the same
    field start to disagree. Every filter except the dates is carried across, so
    "dormant" means "absent from these dates", not "absent from a differently filtered
    view".

    Each comes back with zero presence and the archive's own share, momentum and
    last-seen date attached, which is all :func:`ranking.rank_entities` needs to order
    them.
    """
    span_from, span_to, _count = archive_span(tournaments, trend_filter)
    start, end = parse_date(span_from), parse_date(span_to)
    if start is None or end is None:
        return []
    wide = TrendFilter(
        from_date=start,
        to_date=end,
        format=trend_filter.format,
        min_players=trend_filter.min_players,
        bucket=trend_filter.bucket,
    )
    if wide.from_date >= trend_filter.from_date and wide.to_date <= trend_filter.to_date:
        return []  # the window already is the archive; nothing can be dormant

    prior = overview(
        decks=decks,
        tournaments=tournaments,
        standing_count_by_tournament=standing_count_by_tournament,
        catalog=catalog,
        trend_filter=wide,
        dimension=dimension,
        limit=_UNLIMITED,
        include_dormant=False,
    )
    last_seen = _last_seen_by_entity(decks, dimension)
    return [
        EntityTrend(
            entity_id=row.entity_id,
            name=row.name,
            deck_count=0,
            event_count=0,
            share=0.0,
            momentum=None,
            confidence="limited",
            points=(),
            performance=None,
            # Carried on the rank so `_apply_ranking` can order these without a second
            # channel; the score itself is decided there, not here.
            rank=Rank(
                entity_id=row.entity_id, position=0, score=0.0, tier=TIER_LAST,
                ranked=False, presence_points=0.0, breadth_points=0.0,
                momentum_points=0.0, prior_share=row.share,
                prior_momentum=row.momentum,
                last_seen=last_seen.get(row.entity_id, ""),
            ),
        )
        for row in prior.series
        if row.entity_id not in present
    ]


def _last_seen_by_entity(decks: Iterable[MetaDeck], dimension: Dimension) -> dict[str, str]:
    """The most recent tournament date each entity appeared on."""
    out: dict[str, str] = {}
    for deck in decks:
        entity_id = _entity_id(deck, dimension)
        date = deck.provenance.tournament_date or deck.provenance.published_at
        if not entity_id or not date:
            continue
        if date > out.get(entity_id, ""):
            out[entity_id] = date
    return out


def overview(
    *,
    decks: Iterable[MetaDeck],
    tournaments: Iterable[Tournament],
    standing_count_by_tournament: Mapping[str, int],
    catalog: Catalog,
    trend_filter: TrendFilter,
    dimension: Dimension = "champion",
    limit: int = 12,
    standings: Iterable[Standing] = (),
    eras: Eras | None = None,
    era_id: str = "",
    include_dormant: bool = False,
) -> TrendOverview:
    """Share of the field by entity, and -- where the sample allows -- how it fared.

    ``standings`` and ``eras`` are optional so every existing caller keeps working: a
    view that only wants presence passes neither and gets ``performance=None`` on every
    series, which is honestly "not measured" rather than a zero.

    ``include_dormant`` adds the entities the *archive* knows but this window does not,
    scored 0 and ordered by what the archive still says about them. Off by default so
    the shape of the response only changes for a caller that asked: a page charting a
    fortnight does not necessarily want thirty legends at zero appended to it.
    """
    all_tournaments = list(tournaments)
    scoped = _tournaments_in_scope(all_tournaments, trend_filter)
    tournament_map = {row.slug: row for row in scoped}
    eligible = _eligible_decks(decks, tournament_map)
    periods = _periods(trend_filter.from_date, trend_filter.to_date, trend_filter.bucket)

    total_by_period: Counter[str] = Counter()
    entity_by_period: dict[str, Counter[str]] = defaultdict(Counter)
    entity_decks: Counter[str] = Counter()
    entity_events: dict[str, set[str]] = defaultdict(set)
    names: dict[str, str] = {}

    for deck in eligible:
        entity_id = _entity_id(deck, dimension)
        if not entity_id:
            continue
        parsed = parse_date(deck.provenance.tournament_date)
        if parsed is None:
            continue
        period = _period(parsed, trend_filter.bucket)
        total_by_period[period] += 1
        entity_by_period[entity_id][period] += 1
        entity_decks[entity_id] += 1
        entity_events[entity_id].add(deck.provenance.tournament_slug)
        names.setdefault(entity_id, _entity_name(deck, dimension, catalog))

    table: PerformanceTable | None = None
    if eras is not None:
        table = performance_table(
            decks=decks,
            tournaments=all_tournaments,
            standings=standings,
            catalog=catalog,
            trend_filter=trend_filter,
            eras=eras,
            era_id=era_id,
            dimension=dimension,
        )

    players, _published, coverage = _coverage(scoped)
    ranked = sorted(entity_decks, key=lambda key: (-entity_decks[key], names.get(key, key)))[:limit]
    series: list[EntityTrend] = []
    total_eligible = sum(entity_decks.values())
    for entity_id in ranked:
        points = tuple(
            TrendPoint(
                period=period,
                decks=entity_by_period[entity_id][period],
                total_decks=total_by_period[period],
                share=(
                    entity_by_period[entity_id][period] / total_by_period[period]
                    if total_by_period[period]
                    else 0.0
                ),
                charted=total_by_period[period] >= MIN_DECKS_FOR_CHART_POINT,
            )
            for period in periods
        )
        # Movement waits for two genuinely usable intervals; the raw points remain in
        # the response for clients that want to explain the partial sample.
        nonempty = [
            point for point in points if point.total_decks >= MIN_DECKS_FOR_MOMENTUM
        ]
        momentum = (
            nonempty[-1].share - nonempty[-2].share if len(nonempty) >= 2 else None
        )
        series.append(
            EntityTrend(
                entity_id=entity_id,
                name=names.get(entity_id, entity_id),
                deck_count=entity_decks[entity_id],
                event_count=len(entity_events[entity_id]),
                share=entity_decks[entity_id] / total_eligible if total_eligible else 0.0,
                momentum=momentum,
                confidence=_confidence(entity_decks[entity_id], len(entity_events[entity_id]), coverage),
                points=points,
                performance=table.get(entity_id) if table else None,
            )
        )

    if include_dormant:
        series.extend(
            _dormant_series(
                decks=decks,
                tournaments=all_tournaments,
                standing_count_by_tournament=standing_count_by_tournament,
                catalog=catalog,
                trend_filter=trend_filter,
                dimension=dimension,
                present=set(entity_decks),
            )
        )

    series = _apply_ranking(series)

    formats = tuple(sorted({row.format for row in all_tournaments if row.format}))
    span = archive_span(all_tournaments, trend_filter)
    return TrendOverview(
        from_date=trend_filter.from_date.isoformat(),
        to_date=trend_filter.to_date.isoformat(),
        format=trend_filter.format,
        dimension=dimension,
        tournament_count=len(scoped),
        standing_count=sum(standing_count_by_tournament.get(row.slug, 0) for row in scoped),
        published_deck_count=len(eligible),
        charted_deck_count=total_eligible,
        known_field_players=players,
        published_coverage=coverage,
        formats=formats,
        archive_from=span[0],
        archive_to=span[1],
        archive_tournament_count=span[2],
        series=tuple(series),
        performance_basis=table.basis if table else None,
    )
