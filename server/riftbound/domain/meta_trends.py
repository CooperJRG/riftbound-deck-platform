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


# -- cards --------------------------------------------------------------------
#
# Card-level tracking, which is the granularity the deck builder actually consumes:
# `play_rate`, `copies` and the pairing graph all live at this level. Tracking cards
# rather than only legends and champions is what lets "this card is rising" and "this is
# what people play it with" become build decisions rather than trivia.
#
# One semantic difference runs through everything below, and it is the reason these are
# separate types rather than another `dimension` on `overview()`. A champion's *share*
# is a partition: every charted list has exactly one, so the shares sum to 1. A card's
# *adoption* is not: a list plays forty of them, so adoptions sum to forty-ish. Calling
# both "share" would invite exactly the arithmetic this module exists to prevent, so the
# field is named `adoption` and never mixed with the other.


@dataclass(frozen=True)
class CardPoint:
    period: str
    decks: int
    total_decks: int
    #: Decks playing this card over decks published in the interval. Not a share of the
    #: metagame -- see the note above.
    adoption: float
    charted: bool


@dataclass(frozen=True)
class CardTrend:
    card_id: str
    name: str
    image_url: str
    card_type: str
    rarity: str
    cost: int | None
    domains: tuple[str, ...]
    decks: int
    adoption: float
    average_copies: float
    event_count: int
    momentum: float | None
    confidence: str
    points: tuple[CardPoint, ...]


@dataclass(frozen=True)
class CardTrendOverview:
    from_date: str
    to_date: str
    format: str
    tournament_count: int
    published_deck_count: int
    charted_deck_count: int
    known_field_players: int
    published_coverage: float
    series: tuple[CardTrend, ...]


@dataclass(frozen=True)
class CardHome:
    """A legend or champion that plays this card, and how much of its use they are."""
    entity_id: str
    name: str
    image_url: str
    decks: int
    share_of_card: float


@dataclass(frozen=True)
class CardPartner:
    """A card played alongside this one.

    The bridge to deck building: this is the same pairing signal `deck_builder` fills
    from, shown to the player rather than only used behind their back. `lift` above 1
    means the field pairs them deliberately; near 1 means they merely both turn up.
    """
    card_id: str
    name: str
    image_url: str
    together: int
    together_rate: float
    lift: float


@dataclass(frozen=True)
class CardDetail:
    trend: CardTrend
    #: How many copies decks run, as (copies, decks). A card played as a one-of is a
    #: different card to one played as a three-of, and the average hides that.
    copies_split: tuple[tuple[int, int], ...]
    legends: tuple[CardHome, ...]
    champions: tuple[CardHome, ...]
    partners: tuple[CardPartner, ...]
    recent_decks: tuple[TrendDeck, ...]


def _card_counts(deck: MetaDeck) -> dict[str, int]:
    """Every card a deck plays and how many, across the zones worth tracking."""
    counts = dict(deck.deck.main)
    for card_id, qty in deck.deck.runes.items():
        counts[card_id] = counts.get(card_id, 0) + qty
    for card_id in deck.deck.battlefields:
        counts[card_id] = counts.get(card_id, 0) + 1
    return counts


def _card_facts(card_id: str, catalog: Catalog) -> tuple[str, str, int | None, tuple[str, ...]]:
    card = catalog.get(card_id)
    if card is None:
        return ("", "", None, ())
    return (card.card_type, card.rarity, card.cost, tuple(card.domains))


def card_trends(
    *,
    decks: Iterable[MetaDeck],
    tournaments: Iterable[Tournament],
    catalog: Catalog,
    trend_filter: TrendFilter,
    limit: int = 40,
    card_type: str = "",
) -> CardTrendOverview:
    """How often the field plays each card, and which way that is moving."""
    all_tournaments = list(tournaments)
    scoped = _tournaments_in_scope(all_tournaments, trend_filter)
    tournament_map = {row.slug: row for row in scoped}
    eligible = _eligible_decks(decks, tournament_map)
    periods = _periods(trend_filter.from_date, trend_filter.to_date, trend_filter.bucket)

    total_by_period: Counter[str] = Counter()
    card_by_period: dict[str, Counter[str]] = defaultdict(Counter)
    card_decks: Counter[str] = Counter()
    card_copies: Counter[str] = Counter()
    card_events: dict[str, set[str]] = defaultdict(set)
    charted = 0

    for deck in eligible:
        parsed = parse_date(deck.provenance.tournament_date)
        if parsed is None:
            continue
        period = _period(parsed, trend_filter.bucket)
        total_by_period[period] += 1
        charted += 1
        for card_id, copies in _card_counts(deck).items():
            card_by_period[card_id][period] += 1
            card_decks[card_id] += 1
            card_copies[card_id] += copies
            card_events[card_id].add(deck.provenance.tournament_slug)

    wanted = card_type.casefold()
    ranked = sorted(card_decks, key=lambda key: (-card_decks[key], key))
    players, _published, coverage = _coverage(scoped)

    series: list[CardTrend] = []
    for card_id in ranked:
        if wanted and _card_facts(card_id, catalog)[0].casefold() != wanted:
            continue
        if len(series) >= limit:
            break
        series.append(
            _card_trend(
                card_id, catalog, periods, card_by_period[card_id], total_by_period,
                decks_played=card_decks[card_id],
                copies=card_copies[card_id],
                events=len(card_events[card_id]),
                charted=charted,
                coverage=coverage,
            )
        )

    return CardTrendOverview(
        from_date=trend_filter.from_date.isoformat(),
        to_date=trend_filter.to_date.isoformat(),
        format=trend_filter.format,
        tournament_count=len(scoped),
        published_deck_count=len(eligible),
        charted_deck_count=charted,
        known_field_players=players,
        published_coverage=coverage,
        series=tuple(series),
    )


def _card_trend(
    card_id: str,
    catalog: Catalog,
    periods: list[str],
    by_period: Counter[str],
    total_by_period: Counter[str],
    *,
    decks_played: int,
    copies: int,
    events: int,
    charted: int,
    coverage: float,
) -> CardTrend:
    points = tuple(
        CardPoint(
            period=period,
            decks=by_period[period],
            total_decks=total_by_period[period],
            adoption=by_period[period] / total_by_period[period] if total_by_period[period] else 0.0,
            charted=total_by_period[period] >= MIN_DECKS_FOR_CHART_POINT,
        )
        for period in periods
    )
    usable = [p for p in points if p.total_decks >= MIN_DECKS_FOR_MOMENTUM]
    kind, rarity, cost, domains = _card_facts(card_id, catalog)
    return CardTrend(
        card_id=card_id,
        name=_name(card_id, catalog),
        image_url=_image(card_id, catalog),
        card_type=kind,
        rarity=rarity,
        cost=cost,
        domains=domains,
        decks=decks_played,
        adoption=decks_played / charted if charted else 0.0,
        average_copies=copies / decks_played if decks_played else 0.0,
        event_count=events,
        momentum=usable[-1].adoption - usable[-2].adoption if len(usable) >= 2 else None,
        confidence=_confidence(decks_played, events, coverage),
        points=points,
    )


def card_detail(
    *,
    card_id: str,
    decks: Iterable[MetaDeck],
    tournaments: Iterable[Tournament],
    catalog: Catalog,
    trend_filter: TrendFilter,
    partner_limit: int = 12,
    home_limit: int = 8,
) -> CardDetail | None:
    """Everything the field can tell us about one card.

    Returns None when nothing in the window plays it -- an honest absence rather than a
    page of zeroes that reads like a result.
    """
    scoped = _tournaments_in_scope(list(tournaments), trend_filter)
    tournament_map = {row.slug: row for row in scoped}
    eligible = _eligible_decks(decks, tournament_map)
    periods = _periods(trend_filter.from_date, trend_filter.to_date, trend_filter.bucket)

    total_by_period: Counter[str] = Counter()
    by_period: Counter[str] = Counter()
    copies_split: Counter[int] = Counter()
    legends: Counter[str] = Counter()
    champions: Counter[str] = Counter()
    partners: Counter[str] = Counter()
    partner_totals: Counter[str] = Counter()
    events: set[str] = set()
    playing: list[MetaDeck] = []
    charted = 0
    copies_total = 0

    for deck in eligible:
        parsed = parse_date(deck.provenance.tournament_date)
        if parsed is None:
            continue
        charted += 1
        total_by_period[_period(parsed, trend_filter.bucket)] += 1
        counts = _card_counts(deck)
        # Every card's own frequency, needed for the lift denominator below.
        for other in counts:
            partner_totals[other] += 1
        if card_id not in counts:
            continue

        by_period[_period(parsed, trend_filter.bucket)] += 1
        copies_split[counts[card_id]] += 1
        copies_total += counts[card_id]
        events.add(deck.provenance.tournament_slug)
        playing.append(deck)
        if deck.deck.legend_id:
            legends[deck.deck.legend_id] += 1
        if deck.deck.champion_id:
            champions[deck.deck.champion_id] += 1
        for other in counts:
            if other != card_id:
                partners[other] += 1

    played = len(playing)
    if played == 0:
        return None

    _players, _published, coverage = _coverage(scoped)
    trend = _card_trend(
        card_id, catalog, periods, by_period, total_by_period,
        decks_played=played, copies=copies_total, events=len(events),
        charted=charted, coverage=coverage,
    )

    def homes(counts: Counter[str]) -> tuple[CardHome, ...]:
        return tuple(
            CardHome(
                entity_id=entity_id,
                name=_name(entity_id, catalog),
                image_url=_image(entity_id, catalog),
                decks=n,
                share_of_card=n / played,
            )
            for entity_id, n in counts.most_common(home_limit)
        )

    # Lift, not raw co-occurrence: a staple everything plays would otherwise top every
    # card's partner list and tell nobody anything.
    ranked_partners: list[CardPartner] = []
    for other, together in partners.most_common():
        base = partner_totals[other] / charted if charted else 0.0
        rate = together / played
        if base <= 0:
            continue
        ranked_partners.append(
            CardPartner(
                card_id=other,
                name=_name(other, catalog),
                image_url=_image(other, catalog),
                together=together,
                together_rate=rate,
                lift=rate / base,
            )
        )
    ranked_partners.sort(key=lambda p: (-p.together_rate * p.lift, p.name))

    recent = sorted(
        playing,
        key=lambda row: (row.provenance.tournament_date, -row.provenance.placement),
        reverse=True,
    )[:10]

    return CardDetail(
        trend=trend,
        copies_split=tuple(sorted(copies_split.items())),
        legends=homes(legends),
        champions=homes(champions),
        partners=tuple(ranked_partners[:partner_limit]),
        recent_decks=tuple(_trend_deck(row, catalog) for row in recent),
    )
