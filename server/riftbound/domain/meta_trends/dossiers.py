"""Everything the field can say about one champion, legend or tournament.

The drill-downs behind a ranking. Each answers "where did this number come from" with
placements, pairings, card adoption and the actual lists, because a ranking nobody can
audit is a ranking nobody should trust.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from ..cards import Catalog
from ..meta import MetaDeck, Tournament
from .common import (
    CardAdoption,
    EntityTrend,
    Pairing,
    TrendDeck,
    TrendFilter,
    _confidence,
    _eligible_decks,
    _image,
    _name,
    _tournaments_in_scope,
    _trend_deck,
)
from .entities import overview


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
