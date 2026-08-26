"""Honest, presentation-neutral tournament trend aggregation.

The meta snapshot contains two different populations: every known tournament entrant,
and the much smaller set of entrants whose complete deck list was published.  Champion
and archetype claims can only be made about the latter.  This module keeps that
distinction explicit so the UI never turns "48 published lists" into "the 2,224-player
field" by accident.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

from .cards import Catalog
from .meta import MetaDeck, Tournament

Dimension = Literal["champion", "legend", "archetype"]
Bucket = Literal["week", "month"]

#: Complete lists an interval needs before movement may be computed from it.
#:
#: A three-list partial week can swing a share by fifty points while saying almost
#: nothing, and a number that moves for no reason is worse than no number: people act on
#: it. Momentum needs two intervals this size, so a quiet week produces silence rather
#: than a dramatic and meaningless arrow.
MIN_DECKS_FOR_MOMENTUM = 20

#: Complete lists an interval needs before it is drawn as a charted point.
#:
#: Lower than the momentum bar on purpose. Showing a thin interval is defensible when
#: the reader can see the whole line and judge it; deriving a direction from one is not.
#: Exported so the client plots exactly what the server considers plottable, rather than
#: keeping its own copy of the number.
MIN_DECKS_FOR_CHART_POINT = 10

#: Thresholds behind the confidence label. Deliberately three coarse buckets rather than
#: a percentage: a false precision on a sample this size would be its own dishonesty.
HIGH_CONFIDENCE_DECKS = 50
HIGH_CONFIDENCE_EVENTS = 6
HIGH_CONFIDENCE_COVERAGE = 0.15
MODERATE_CONFIDENCE_DECKS = 15
MODERATE_CONFIDENCE_EVENTS = 3


@dataclass(frozen=True)
class TrendFilter:
    from_date: date
    to_date: date
    format: str = ""
    min_players: int = 0
    bucket: Bucket = "week"


@dataclass(frozen=True)
class TrendPoint:
    period: str
    decks: int
    total_decks: int
    share: float
    #: Whether this interval carries enough lists to be worth drawing as a point.
    #:
    #: Decided here rather than in the client so the threshold lives next to the tests
    #: that pin it. A client keeping its own copy of the number is two policies that
    #: drift apart, and only one of them is checked.
    charted: bool = False


@dataclass(frozen=True)
class EntityTrend:
    entity_id: str
    name: str
    deck_count: int
    event_count: int
    share: float
    momentum: float | None
    confidence: str
    points: tuple[TrendPoint, ...]


@dataclass(frozen=True)
class TrendOverview:
    from_date: str
    to_date: str
    format: str
    dimension: Dimension
    tournament_count: int
    standing_count: int
    published_deck_count: int
    #: Published lists that resolved to an entity in *this* dimension, and therefore the
    #: population every share below is measured against.
    #:
    #: Lower than ``published_deck_count`` whenever a list did not resolve -- a deck
    #: whose champion the source never recorded is dropped from champion shares rather
    #: than counted as a zero, which is right, but it means the headline "published
    #: lists" figure is not the denominator. Reporting only the larger number invites a
    #: client to divide by it and quietly print the wrong percentage.
    charted_deck_count: int
    known_field_players: int
    published_coverage: float
    formats: tuple[str, ...]
    series: tuple[EntityTrend, ...]


@dataclass(frozen=True)
class Pairing:
    entity_id: str
    name: str
    image_url: str
    decks: int
    share: float


@dataclass(frozen=True)
class CardAdoption:
    card_id: str
    name: str
    image_url: str
    decks: int
    inclusion: float
    average_copies: float


@dataclass(frozen=True)
class TrendDeck:
    deck_id: str
    name: str
    legend_id: str
    legend_name: str
    champion_id: str
    champion_name: str
    legend_image_url: str
    champion_image_url: str
    tournament_slug: str
    tournament_name: str
    tournament_date: str
    placement: int
    field_size: int
    placement_strength: float
    source_url: str


@dataclass(frozen=True)
class ChampionMeta:
    champion_id: str
    champion_name: str
    image_url: str
    domains: tuple[str, ...]
    overview: EntityTrend
    tournament_count: int
    top_eight: int
    top_sixteen: int
    best_placement: int
    best_field_size: int
    average_placement_strength: float
    pairings: tuple[Pairing, ...]
    cards: tuple[CardAdoption, ...]
    recent_decks: tuple[TrendDeck, ...]


@dataclass(frozen=True)
class LegendMeta:
    legend_id: str
    legend_name: str
    image_url: str
    domains: tuple[str, ...]
    overview: EntityTrend
    tournament_count: int
    top_eight: int
    top_sixteen: int
    best_placement: int
    best_field_size: int
    average_placement_strength: float
    champions: tuple[Pairing, ...]
    cards: tuple[CardAdoption, ...]
    recent_decks: tuple[TrendDeck, ...]


@dataclass(frozen=True)
class TournamentEntity:
    entity_id: str
    name: str
    decks: int
    share: float


@dataclass(frozen=True)
class TournamentDetail:
    slug: str
    name: str
    date: str
    format: str
    players: int
    winner: str
    decks_published: int
    known_deck_count: int
    #: Complete lists that named a champion, and the denominator of every share in
    #: ``champions``. Lower than ``known_deck_count`` when a list did not resolve one.
    charted_deck_count: int
    published_coverage: float
    confidence: str
    champions: tuple[TournamentEntity, ...]
    decks: tuple[TrendDeck, ...]


def parse_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def default_range(tournaments: Iterable[Tournament], days: int = 90) -> tuple[date, date]:
    dates = [parsed for row in tournaments if (parsed := parse_date(row.date))]
    end = max(dates, default=date.today())
    return end - timedelta(days=max(1, days) - 1), end


def _period(value: date, bucket: Bucket) -> str:
    if bucket == "month":
        return value.replace(day=1).isoformat()
    return (value - timedelta(days=value.weekday())).isoformat()


def _periods(start: date, end: date, bucket: Bucket) -> list[str]:
    cursor = start.replace(day=1) if bucket == "month" else start - timedelta(days=start.weekday())
    out: list[str] = []
    while cursor <= end:
        out.append(cursor.isoformat())
        if bucket == "month":
            cursor = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
        else:
            cursor += timedelta(days=7)
    return out


def _tournaments_in_scope(
    tournaments: Iterable[Tournament], trend_filter: TrendFilter
) -> list[Tournament]:
    wanted_format = trend_filter.format.casefold()
    out: list[Tournament] = []
    for tournament in tournaments:
        parsed = parse_date(tournament.date)
        if parsed is None or not trend_filter.from_date <= parsed <= trend_filter.to_date:
            continue
        if tournament.players < trend_filter.min_players:
            continue
        if wanted_format and tournament.format.casefold() != wanted_format:
            continue
        out.append(tournament)
    return out


def _eligible_decks(
    decks: Iterable[MetaDeck], tournaments: Mapping[str, Tournament]
) -> list[MetaDeck]:
    return [
        deck
        for deck in decks
        if deck.is_complete
        and deck.provenance.is_tournament
        and deck.provenance.tournament_slug in tournaments
        and parse_date(deck.provenance.tournament_date) is not None
    ]


def _entity_id(deck: MetaDeck, dimension: Dimension) -> str:
    if dimension == "champion":
        return deck.deck.champion_id
    if dimension == "legend":
        return deck.deck.legend_id
    return deck.archetype_id


def _name(card_id: str, catalog: Catalog) -> str:
    card = catalog.get(card_id)
    return card.name if card else card_id or "Unknown"


def _image(card_id: str, catalog: Catalog) -> str:
    card = catalog.get(card_id)
    return card.image_url if card else ""


def _entity_name(deck: MetaDeck, dimension: Dimension, catalog: Catalog) -> str:
    if dimension == "champion":
        return _name(deck.deck.champion_id, catalog)
    if dimension == "legend":
        return _name(deck.deck.legend_id, catalog)
    names = [_name(deck.deck.legend_id, catalog)]
    if deck.deck.champion_id:
        names.append(_name(deck.deck.champion_id, catalog))
    return " · ".join(names)


def _confidence(deck_count: int, event_count: int, coverage: float) -> str:
    if (
        deck_count >= HIGH_CONFIDENCE_DECKS
        and event_count >= HIGH_CONFIDENCE_EVENTS
        and coverage >= HIGH_CONFIDENCE_COVERAGE
    ):
        return "high"
    if deck_count >= MODERATE_CONFIDENCE_DECKS and event_count >= MODERATE_CONFIDENCE_EVENTS:
        return "moderate"
    return "limited"


def _coverage(tournaments: Iterable[Tournament]) -> tuple[int, int, float]:
    rows = list(tournaments)
    players = sum(max(0, row.players) for row in rows)
    published = sum(max(0, min(row.decks_published, row.players)) for row in rows)
    return players, published, published / players if players else 0.0


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
        series=tuple(series),
    )


def _trend_deck(deck: MetaDeck, catalog: Catalog) -> TrendDeck:
    placement = deck.provenance.placement
    field_size = deck.provenance.field_size
    strength = (
        1.0 - ((placement - 1) / field_size)
        if placement > 0 and field_size > 0
        else 0.0
    )
    return TrendDeck(
        deck_id=deck.deck_id,
        name=deck.deck.name,
        legend_id=deck.deck.legend_id,
        legend_name=_name(deck.deck.legend_id, catalog),
        champion_id=deck.deck.champion_id,
        champion_name=_name(deck.deck.champion_id, catalog),
        legend_image_url=_image(deck.deck.legend_id, catalog),
        champion_image_url=_image(deck.deck.champion_id, catalog),
        tournament_slug=deck.provenance.tournament_slug,
        tournament_name=deck.provenance.tournament_name,
        tournament_date=deck.provenance.tournament_date,
        placement=placement,
        field_size=field_size,
        placement_strength=max(0.0, min(1.0, strength)),
        source_url=deck.provenance.url,
    )


def champion_meta(
    *,
    champion_id: str,
    decks: Iterable[MetaDeck],
    tournaments: Iterable[Tournament],
    standing_count_by_tournament: Mapping[str, int],
    catalog: Catalog,
    trend_filter: TrendFilter,
) -> ChampionMeta | None:
    all_decks = list(decks)
    summary = overview(
        decks=all_decks,
        tournaments=tournaments,
        standing_count_by_tournament=standing_count_by_tournament,
        catalog=catalog,
        trend_filter=trend_filter,
        dimension="champion",
        limit=10_000,
    )
    entity = next((row for row in summary.series if row.entity_id == champion_id), None)
    if entity is None:
        return None

    scoped = _tournaments_in_scope(tournaments, trend_filter)
    tournament_map = {row.slug: row for row in scoped}
    matches = [
        row for row in _eligible_decks(all_decks, tournament_map)
        if row.deck.champion_id == champion_id
    ]
    legend_counts = Counter(row.deck.legend_id for row in matches if row.deck.legend_id)
    pairings = tuple(
        Pairing(
            entity_id=legend_id,
            name=_name(legend_id, catalog),
            image_url=_image(legend_id, catalog),
            decks=count,
            share=count / len(matches) if matches else 0.0,
        )
        for legend_id, count in legend_counts.most_common(8)
    )

    card_decks: Counter[str] = Counter()
    card_copies: Counter[str] = Counter()
    for row in matches:
        for card_id, copies in row.deck.main.items():
            if card_id == champion_id:
                continue
            card_decks[card_id] += 1
            card_copies[card_id] += copies
    cards = tuple(
        CardAdoption(
            card_id=card_id,
            name=_name(card_id, catalog),
            image_url=_image(card_id, catalog),
            decks=count,
            inclusion=count / len(matches) if matches else 0.0,
            average_copies=card_copies[card_id] / count,
        )
        for card_id, count in card_decks.most_common(16)
    )

    placed = [row for row in matches if row.provenance.placement > 0]
    strengths = [_trend_deck(row, catalog).placement_strength for row in placed]
    best = max(placed, key=lambda row: _trend_deck(row, catalog).placement_strength, default=None)
    recent = sorted(
        matches,
        key=lambda row: (
            row.provenance.tournament_date,
            _trend_deck(row, catalog).placement_strength,
        ),
        reverse=True,
    )[:8]
    return ChampionMeta(
        champion_id=champion_id,
        champion_name=_name(champion_id, catalog),
        image_url=_image(champion_id, catalog),
        domains=(catalog.get(champion_id).domains if catalog.get(champion_id) else ()),
        overview=entity,
        tournament_count=len({row.provenance.tournament_slug for row in matches}),
        top_eight=sum(1 for row in placed if row.provenance.placement <= 8),
        top_sixteen=sum(1 for row in placed if row.provenance.placement <= 16),
        best_placement=best.provenance.placement if best else 0,
        best_field_size=best.provenance.field_size if best else 0,
        average_placement_strength=sum(strengths) / len(strengths) if strengths else 0.0,
        pairings=pairings,
        cards=cards,
        recent_decks=tuple(_trend_deck(row, catalog) for row in recent),
    )


def legend_meta(
    *,
    legend_id: str,
    decks: Iterable[MetaDeck],
    tournaments: Iterable[Tournament],
    standing_count_by_tournament: Mapping[str, int],
    catalog: Catalog,
    trend_filter: TrendFilter,
) -> LegendMeta | None:
    """A visual, contextual dossier for one legend.

    Champion variants stay separate from staples: a player looking at a legend needs
    to understand *how* it is being built before a flat card-frequency table is useful.
    """
    all_decks = list(decks)
    summary = overview(
        decks=all_decks,
        tournaments=tournaments,
        standing_count_by_tournament=standing_count_by_tournament,
        catalog=catalog,
        trend_filter=trend_filter,
        dimension="legend",
        limit=10_000,
    )
    entity = next((row for row in summary.series if row.entity_id == legend_id), None)
    if entity is None:
        return None

    scoped = _tournaments_in_scope(tournaments, trend_filter)
    tournament_map = {row.slug: row for row in scoped}
    matches = [
        row for row in _eligible_decks(all_decks, tournament_map)
        if row.deck.legend_id == legend_id
    ]
    champion_counts = Counter(row.deck.champion_id for row in matches if row.deck.champion_id)
    champions = tuple(
        Pairing(
            entity_id=champion_id,
            name=_name(champion_id, catalog),
            image_url=_image(champion_id, catalog),
            decks=count,
            share=count / len(matches) if matches else 0.0,
        )
        for champion_id, count in champion_counts.most_common(10)
    )

    card_decks: Counter[str] = Counter()
    card_copies: Counter[str] = Counter()
    for row in matches:
        for card_id, copies in row.deck.main.items():
            card = catalog.get(card_id)
            if card and card.super_type == "Champion":
                continue
            card_decks[card_id] += 1
            card_copies[card_id] += copies
    cards = tuple(
        CardAdoption(
            card_id=card_id,
            name=_name(card_id, catalog),
            image_url=_image(card_id, catalog),
            decks=count,
            inclusion=count / len(matches) if matches else 0.0,
            average_copies=card_copies[card_id] / count,
        )
        for card_id, count in card_decks.most_common(16)
    )

    placed = [row for row in matches if row.provenance.placement > 0]
    strengths = [_trend_deck(row, catalog).placement_strength for row in placed]
    best = max(placed, key=lambda row: _trend_deck(row, catalog).placement_strength, default=None)
    recent = sorted(
        matches,
        key=lambda row: (
            row.provenance.tournament_date,
            _trend_deck(row, catalog).placement_strength,
        ),
        reverse=True,
    )[:10]
    legend = catalog.get(legend_id)
    return LegendMeta(
        legend_id=legend_id,
        legend_name=_name(legend_id, catalog),
        image_url=_image(legend_id, catalog),
        domains=legend.domains if legend else (),
        overview=entity,
        tournament_count=len({row.provenance.tournament_slug for row in matches}),
        top_eight=sum(1 for row in placed if row.provenance.placement <= 8),
        top_sixteen=sum(1 for row in placed if row.provenance.placement <= 16),
        best_placement=best.provenance.placement if best else 0,
        best_field_size=best.provenance.field_size if best else 0,
        average_placement_strength=sum(strengths) / len(strengths) if strengths else 0.0,
        champions=champions,
        cards=cards,
        recent_decks=tuple(_trend_deck(row, catalog) for row in recent),
    )


def tournament_detail(
    *, slug: str, tournaments: Iterable[Tournament], decks: Iterable[MetaDeck], catalog: Catalog
) -> TournamentDetail | None:
    tournament = next((row for row in tournaments if row.slug == slug), None)
    if tournament is None:
        return None
    matches = [
        row for row in decks
        if row.is_complete and row.provenance.tournament_slug == slug
    ]
    champion_counts = Counter(row.deck.champion_id for row in matches if row.deck.champion_id)
    # Divide by the lists that actually named a champion, not by every complete list.
    # A list whose champion the source never recorded cannot be evidence for or against
    # any champion, so including it in the denominator shrinks every share toward zero:
    # at one real event this had the distribution summing to 0.14, which reads as
    # "14% played Master Yi" when in truth every list that named a champion did.
    charted = sum(champion_counts.values())
    champions = tuple(
        TournamentEntity(
            entity_id=champion_id,
            name=_name(champion_id, catalog),
            decks=count,
            share=count / charted if charted else 0.0,
        )
        for champion_id, count in champion_counts.most_common()
    )
    coverage = (
        min(tournament.decks_published, tournament.players) / tournament.players
        if tournament.players
        else 0.0
    )
    ordered = sorted(
        matches,
        key=lambda row: (
            row.provenance.placement <= 0,
            row.provenance.placement or 10**9,
        ),
    )
    return TournamentDetail(
        slug=tournament.slug,
        name=tournament.name,
        date=tournament.date,
        format=tournament.format,
        players=tournament.players,
        winner=tournament.winner,
        decks_published=tournament.decks_published,
        known_deck_count=len(matches),
        charted_deck_count=charted,
        published_coverage=coverage,
        confidence=_confidence(len(matches), 1, coverage),
        champions=champions,
        decks=tuple(_trend_deck(row, catalog) for row in ordered[:30]),
    )
