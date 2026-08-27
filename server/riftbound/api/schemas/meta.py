"""The competitive meta: decks, archetypes, tournaments and trends.

Every deck carries its provenance and score breakdown, because a ranking nobody can
argue with is a ranking nobody should trust.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from .base import ApiModel
from .decks import CoverageView

# -- meta ---------------------------------------------------------------------


class ProvenanceView(ApiModel):
    """Where a meta deck came from, and what backs it."""
    source: str
    url: str
    evidence: str
    summary: str            # human-readable, e.g. "3rd of 257 at Convergence #2"
    author: str
    published_at: str
    views: int
    tournament_slug: str
    tournament_name: str
    tournament_date: str
    placement: int
    field_size: int


class ScoreView(ApiModel):
    """A ranking with its parts, so the UI can explain itself."""
    total: float
    evidence: float
    placement: float
    recency: float
    popularity: float


class MetaDeckView(ApiModel):
    deck_id: str
    name: str
    legend_id: str
    legend_name: str
    champion_id: str
    champion_name: str
    archetype_id: str
    domains: list[str]
    main_total: int
    provenance: ProvenanceView
    score: ScoreView
    coverage: CoverageView
    unresolved: list[str]
    deck: dict[str, Any]


class ArchetypeView(ApiModel):
    archetype_id: str
    name: str
    legend_id: str
    champion_id: str
    deck_count: int
    tournament_deck_count: int
    best_placement: int
    best_field_size: int
    latest_date: str
    score: float
    best_deck: MetaDeckView | None = None


class TournamentView(ApiModel):
    slug: str
    name: str
    date: str
    format: str
    players: int
    winner: str
    decks_published: int


class TrendPointView(ApiModel):
    period: str
    decks: int
    total_decks: int
    share: float
    #: Whether this interval carries enough lists to be worth drawing. The server owns
    #: the threshold so every client plots the same thing.
    charted: bool


class TrendSeriesView(ApiModel):
    entity_id: str
    name: str
    deck_count: int
    event_count: int
    share: float
    momentum: float | None
    confidence: str
    points: list[TrendPointView]


class TrendOverviewView(ApiModel):
    from_date: str
    to_date: str
    format: str
    dimension: str
    tournament_count: int
    standing_count: int
    published_deck_count: int
    #: The population the shares below are actually divided by. Smaller than
    #: `publishedDeckCount` when a list did not resolve to an entity in this dimension.
    charted_deck_count: int
    known_field_players: int
    published_coverage: float
    formats: list[str]
    #: The whole archive's span, regardless of the window shown, so the page can say how
    #: much more there is behind the default range.
    archive_from: str
    archive_to: str
    archive_tournament_count: int
    series: list[TrendSeriesView]


class PairingView(ApiModel):
    entity_id: str
    name: str
    image_url: str
    decks: int
    share: float


class CardAdoptionView(ApiModel):
    card_id: str
    name: str
    image_url: str
    decks: int
    inclusion: float
    average_copies: float


class TrendDeckView(ApiModel):
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


class ChampionMetaView(ApiModel):
    champion_id: str
    champion_name: str
    image_url: str
    domains: list[str]
    overview: TrendSeriesView
    tournament_count: int
    top_eight: int
    top_sixteen: int
    best_placement: int
    best_field_size: int
    average_placement_strength: float
    pairings: list[PairingView]
    cards: list[CardAdoptionView]
    recent_decks: list[TrendDeckView]


class LegendMetaView(ApiModel):
    legend_id: str
    legend_name: str
    image_url: str
    domains: list[str]
    overview: TrendSeriesView
    tournament_count: int
    top_eight: int
    top_sixteen: int
    best_placement: int
    best_field_size: int
    average_placement_strength: float
    champions: list[PairingView]
    cards: list[CardAdoptionView]
    recent_decks: list[TrendDeckView]


class TournamentEntityView(ApiModel):
    entity_id: str
    name: str
    decks: int
    share: float


class TournamentDetailView(ApiModel):
    slug: str
    name: str
    date: str
    format: str
    players: int
    winner: str
    decks_published: int
    known_deck_count: int
    #: Complete lists that named a champion; the denominator of every champion share.
    charted_deck_count: int
    published_coverage: float
    confidence: str
    champions: list[TournamentEntityView]
    decks: list[TrendDeckView]


class AttributionView(ApiModel):
    """A credit the meta data's source requires us to display."""
    source: str
    url: str
    text: str


class MetaStatusView(ApiModel):
    available: bool
    snapshot_id: str
    created_at: str
    deck_count: int
    tournament_count: int
    evidence_counts: dict[str, int]
    warnings: list[str]
    attribution: list[AttributionView] = Field(default_factory=list)


class RefreshRunView(ApiModel):
    """One scheduled harvest, kept whether it worked or not."""
    started_at: str
    finished_at: str
    ok: bool
    promoted: bool
    snapshot_id: str
    deck_count: int
    duration_ms: int
    message: str


class RefreshStatusView(ApiModel):
    """Whether the meta is keeping itself current, and how it is going.

    Exposed because a stale snapshot looks exactly like a fresh one from the outside.
    "Why is the meta old" should be answerable in the UI, not in a log file.
    """
    enabled: bool
    status: str                 # 'idle' | 'running' | 'off'
    interval_hours: float
    next_run_at: str
    runs: int
    failures: int
    consecutive_failures: int
    #: Age of the promoted snapshot in hours, or -1 when there is none.
    snapshot_age_hours: float
    stale: bool
    last_run: RefreshRunView | None = None
    history: list[RefreshRunView] = Field(default_factory=list)
