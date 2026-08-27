"""The vocabulary every trend view shares.

Filters, points, the shapes a series comes back in, and the small decisions that must
be made the same way everywhere: what counts as a usable list, what a period is, and
how confident a sample lets us sound. Split out because three different views depend on
these being identical -- a second opinion about what "eligible" means is how two pages
end up quoting different totals for the same window.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

from ..cards import Catalog
from ..meta import MetaDeck, Tournament

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
    #: The whole archive's span, regardless of the window being shown. Without it the
    #: page cannot say "90 days of the 13 months you have", and a reader has no way to
    #: know there is more behind the default.
    archive_from: str
    archive_to: str
    archive_tournament_count: int
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



def archive_span(
    tournaments: Iterable[Tournament], trend_filter: TrendFilter | None = None
) -> tuple[str, str, int]:
    """How much there is to see if the date window were opened all the way.

    Every filter *except* the dates is applied. That is the whole point of the number:
    it answers "would widening the range show me more", and it has to be comparable with
    the count of what is on screen. Counting every event regardless of size against a
    view filtered to 16+ players produces "showing 124 of 333 -- the whole archive",
    which is two different questions sharing a sentence.
    """
    rows = [row for row in tournaments if parse_date(row.date)]
    if trend_filter is not None:
        wanted = trend_filter.format.casefold()
        rows = [
            row for row in rows
            if row.players >= trend_filter.min_players
            and (not wanted or row.format.casefold() == wanted)
        ]
    if not rows:
        return ("", "", 0)
    dates = sorted(row.date for row in rows)
    return (dates[0], dates[-1], len(rows))



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
