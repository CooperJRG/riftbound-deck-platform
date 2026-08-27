"""Card-level tracking: what is being played, rather than what is winning.

The granularity the deck builder consumes -- play rate, copies, and the pairing graph.

Kept apart from `entities` because one number behaves differently. A champion's *share*
partitions the field; a card's *adoption* does not, since a list plays forty of them.
Sharing a module would invite sharing a label, and sharing a label invites dividing one
by the other.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from ..cards import Catalog
from ..meta import MetaDeck, Tournament
from .common import (
    MIN_DECKS_FOR_CHART_POINT,
    MIN_DECKS_FOR_MOMENTUM,
    TrendDeck,
    TrendFilter,
    _confidence,
    _coverage,
    _eligible_decks,
    _image,
    _name,
    _period,
    _periods,
    _tournaments_in_scope,
    _trend_deck,
    archive_span,
    parse_date,
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
    archive_from: str
    archive_to: str
    archive_tournament_count: int
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

    span = archive_span(all_tournaments, trend_filter)
    return CardTrendOverview(
        from_date=trend_filter.from_date.isoformat(),
        to_date=trend_filter.to_date.isoformat(),
        format=trend_filter.format,
        tournament_count=len(scoped),
        published_deck_count=len(eligible),
        charted_deck_count=charted,
        known_field_players=players,
        published_coverage=coverage,
        archive_from=span[0],
        archive_to=span[1],
        archive_tournament_count=span[2],
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
