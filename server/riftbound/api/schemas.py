"""API request and response models.

Requests are strict (``extra="forbid"``) and accept camelCase from the browser while
staying snake_case in Python -- the one piece of v2's API layer worth keeping.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..domain.availability import DEFAULT_PENALTY, MODES, RULE_KINDS


def _camel(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(word.capitalize() for word in rest)


class ApiModel(BaseModel):
    """Response base: snake_case in Python, camelCase on the wire."""
    model_config = ConfigDict(alias_generator=_camel, populate_by_name=True)


class StrictRequest(BaseModel):
    """Request base: unknown fields are an error, not silently ignored."""
    model_config = ConfigDict(alias_generator=_camel, populate_by_name=True, extra="forbid")


# -- cards --------------------------------------------------------------------


class PrintingView(ApiModel):
    print_id: str
    title: str
    set_code: str
    card_number: str
    rarity: str
    promo: bool
    image_url: str


class CardView(ApiModel):
    card_id: str
    name: str
    card_type: str
    super_type: str
    domains: list[str]
    cost: int | None
    might: int | None
    tags: list[str]
    champion_tags: list[str]
    effect: str
    unique: bool
    rarity: str
    set_codes: list[str]
    image_url: str
    printings: list[PrintingView] = Field(default_factory=list)


class CardAvailabilityView(ApiModel):
    """A card plus how available it is under the active profile."""
    card: CardView
    weight: float
    available: bool
    owned_copies: int
    max_copies: int | None
    reason: str


class CardPage(ApiModel):
    total: int
    offset: int
    limit: int
    cards: list[CardAvailabilityView]


# -- formats ------------------------------------------------------------------


class FormatView(ApiModel):
    format: str
    description: str
    constraints: dict[str, Any]
    banned_card_ids: list[str]


# -- decks --------------------------------------------------------------------


class DeckPayload(StrictRequest):
    name: str = "Untitled Deck"
    format: str = "constructed"
    legend_id: str = ""
    champion_id: str = ""
    main: dict[str, int] = Field(default_factory=dict)
    runes: dict[str, int] = Field(default_factory=dict)
    battlefields: list[str] = Field(default_factory=list)
    sideboard: dict[str, int] = Field(default_factory=dict)


class IssueView(ApiModel):
    code: str
    field: str
    message: str
    rule_refs: list[str]
    card_id: str
    severity: str


class CoverageView(ApiModel):
    total_copies: int
    available_copies: int
    penalised_copies: int
    ratio: float
    complete: bool
    missing: list[dict[str, Any]]


class ValidationView(ApiModel):
    legal: bool
    issues: list[IssueView]
    main_total: int
    rune_total: int
    sideboard_total: int
    battlefield_count: int
    legend_domains: list[str]
    coverage: CoverageView


class DeckSummaryView(ApiModel):
    deck_id: str
    name: str
    format: str
    legend_id: str
    champion_id: str
    main_total: int
    created_at: str
    updated_at: str


class DeckView(ApiModel):
    deck_id: str
    deck: dict[str, Any]
    validation: ValidationView


# -- availability -------------------------------------------------------------


class ExclusionRuleView(ApiModel):
    kind: str
    value: str
    description: str


class ExcludedCardView(ApiModel):
    """An excluded card with its name resolved.

    The server owns the catalogue, so it names these rather than leaving the client to
    display a bare id for any card it has not happened to load.
    """
    card_id: str
    name: str


class AvailabilityView(ApiModel):
    mode: str
    strict: bool
    penalty: float
    description: str
    excluded_cards: list[ExcludedCardView]
    rules: list[ExclusionRuleView]
    owned_card_count: int


class ExclusionRuleInput(StrictRequest):
    kind: str
    value: str = ""


class AvailabilityUpdate(StrictRequest):
    mode: str = Field(default="open")
    strict: bool = False
    penalty: float = DEFAULT_PENALTY
    excluded_card_ids: list[str] = Field(default_factory=list)
    rules: list[ExclusionRuleInput] = Field(default_factory=list)

    def validated_mode(self) -> str:
        if self.mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        return self.mode

    def validated_rules(self) -> list[ExclusionRuleInput]:
        for rule in self.rules:
            if rule.kind not in RULE_KINDS:
                raise ValueError(f"rule kind must be one of {RULE_KINDS}, got {rule.kind!r}")
        return self.rules


# -- data ---------------------------------------------------------------------


class SourceHealthView(ApiModel):
    name: str
    ok: bool
    fetched: int
    accepted: int
    error: str


class BundleView(ApiModel):
    bundle_id: str
    created_at: str
    card_count: int
    printing_count: int
    set_codes: list[str]
    sources: list[SourceHealthView]
    warnings: list[str]


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
