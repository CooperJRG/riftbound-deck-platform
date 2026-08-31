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
    legend_image_url: str
    champion_image_url: str
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


class PerformanceView(ApiModel):
    """How an entity fared, and whether the sample lets us say so.

    ``shown`` is the field a client must branch on. When it is false the rate and the
    interval are still populated -- they are simply not fit to print -- and
    ``withheldReason`` says which threshold was missed, so the page can render "62
    matches so far, needs 200" rather than a blank cell.
    """
    entity_id: str
    name: str
    decks_with_records: int
    matches: int          # every match, draws included
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
    #: True only when the whole 95% interval sits above even. The only claim of "this
    #: wins" the evidence supports.
    separated: bool
    shown: bool
    withheld_reason: str
    #: Plain English, so a client never has to reimplement the thresholds to explain
    #: them. Empty when the rate is shown.
    withheld_detail: str


class PerformanceBasisView(ApiModel):
    """What the win rates are a rate *of*. Rendered beside them, never in a tooltip."""
    era_id: str
    era_name: str
    era_from: str
    era_to: str
    #: False while the era boundary is derived from the archive rather than read off a
    #: published announcement. Shown, so the distinction is not quietly forgotten.
    era_cited: bool
    era_evidence: str
    entities_measured: int
    entities_shown: int
    entities_withheld: int
    decks_with_records: int
    total_matches: int
    published_win_rate: float
    unpublished_win_rate: float
    published_standings: int
    unpublished_standings: int
    publication_gap: float
    #: The sentence that has to appear wherever a rate does.
    caveat: str


class EraView(ApiModel):
    era_id: str
    name: str
    from_date: str
    to_date: str
    is_open: bool
    is_cited: bool
    evidence: str
    bans_introduced: list[str]


class RankView(ApiModel):
    """Where an entity placed in the field, as a number a player can read.

    The scale is 0-100 and both ends mean something: 100 is leading the field on
    presence, event breadth and momentum at once, and 0 is having no lists in the
    selected range at all. The three components sum to `score`, so a card can show its
    own working instead of asking the reader to trust a letter.
    """
    position: int          # 1-based, across the whole field
    score: float           # 0-100
    tier: str              # S / A / B / C / D
    #: False when the entity had no lists in this range. It still gets a position and a
    #: tier -- ordered by what the archive knows -- but its score is 0 by definition,
    #: and a client should say why rather than showing it as a measured worst.
    ranked: bool
    presence_points: float
    breadth_points: float
    momentum_points: float
    #: Only meaningful when `ranked` is false: what the whole archive still says about
    #: an entity this window cannot see, and what orders it against the other dormant
    #: ones.
    prior_share: float
    prior_momentum: float | None
    last_seen: str
    #: The one line a card can print under the number, written server-side so two
    #: clients cannot phrase the same fact differently.
    summary: str


class TrendSeriesView(ApiModel):
    entity_id: str
    name: str
    deck_count: int
    event_count: int
    share: float
    momentum: float | None
    confidence: str
    points: list[TrendPointView]
    #: Performance, kept beside presence and never blended into it. `null` means no
    #: match records reached this entity at all, which is a different statement from
    #: "we have records and they are too thin" -- that arrives as an object with
    #: `shown: false`.
    performance: PerformanceView | None = None
    #: Rank, rating and tier. The series arrives already in rank order.
    rank: RankView | None = None


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
    #: Null when the caller asked for presence only.
    performance_basis: PerformanceBasisView | None = None


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


class MatchupView(ApiModel):
    """One legend's record against one opponent.

    Same contract as :class:`PerformanceView`: ``shown`` is the field to branch on, the
    counts stay populated when it is false, and ``withheldDetail`` explains which
    threshold was missed so no client has to reimplement the policy to describe it.
    """
    legend_id: str
    opponent_id: str
    legend_name: str
    opponent_name: str
    matches: int
    #: Matches with a winner. This source records no draws, so it equals ``matches``.
    decisive: int
    wins: int
    losses: int
    games_won: int
    games_lost: int
    #: Distinct events the pairing was seen at; 0 when the source shipped no breakdown.
    events: int
    win_rate: float
    interval_low: float
    interval_high: float
    #: True only when the whole interval clears even, in either direction. The only
    #: claim of "this is a real edge" the evidence supports.
    separated: bool
    favourable: bool
    unfavourable: bool
    shown: bool
    withheld_reason: str
    withheld_detail: str
    summary: str


class LegendRecordView(ApiModel):
    """One legend's overall record across the same events.

    Reported by the source rather than summed from its matchup row: the overall figure
    includes matches whose opponent's legend was never identified, which cannot appear
    in any cell. The two therefore do not reconcile exactly, and that is correct.
    """
    legend_id: str
    name: str
    image_url: str
    matches: int
    decisive: int
    wins: int
    losses: int
    games_won: int
    games_lost: int
    players: int
    mirror_matches: int
    win_rate: float
    interval_low: float
    interval_high: float
    separated: bool
    shown: bool
    withheld_reason: str
    summary: str


class MatchupBasisView(ApiModel):
    """What the matchup table is a table *of*.

    Carried in the response rather than left to a tooltip. These numbers come from an
    aggregate this project did not compute, over a window it did not choose; a reader
    entitled to trust them is entitled to know that first.
    """
    #: What the upstream project calls its own source, verbatim.
    source_label: str
    attribution: AttributionView | None
    #: The upstream set window, e.g. "set4". **Not** this project's ban era, which is
    #: derived separately and need not align with it.
    set_window: str
    published_at: str
    events: int
    matrix_matches: int
    eligible_matches: int
    legends_measured: int
    legends_shown: int
    cells_measured: int
    cells_shown: int
    min_matches: int
    min_events: int
    summary: str


class MatchupOverviewView(ApiModel):
    """Every legend's overall record, strongest first, plus the basis behind them."""
    available: bool
    basis: MatchupBasisView
    legends: list[LegendRecordView] = Field(default_factory=list)


class LegendMatchupsView(ApiModel):
    """One legend's spread: hardest opponent first, unrated pairings last."""
    legend_id: str
    name: str
    image_url: str
    record: LegendRecordView | None
    basis: MatchupBasisView
    matchups: list[MatchupView] = Field(default_factory=list)


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
