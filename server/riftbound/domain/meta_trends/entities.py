"""Share of the field, by champion, legend or archetype.

A *share* here is a partition: every charted list has exactly one champion, so the
shares sum to 1. That is what separates this module from `cards`, where they do not.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping

from ..cards import Catalog
from ..meta import MetaDeck, Tournament
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


def overview(
    *,
    decks: Iterable[MetaDeck],
    tournaments: Iterable[Tournament],
    standing_count_by_tournament: Mapping[str, int],
    catalog: Catalog,
    trend_filter: TrendFilter,
    dimension: Dimension = "champion",
    limit: int = 12,
) -> TrendOverview:
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
            )
        )

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
    )
