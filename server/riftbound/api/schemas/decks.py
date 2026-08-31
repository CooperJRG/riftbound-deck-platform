"""Deck payloads, and what validation says about them.

Legality and coverage are separate fields on purpose: "this deck is illegal" and "this
deck is legal but you are missing four cards" are different problems with different
answers, and v2 conflated them.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from .base import ApiModel, StrictRequest
from .scoring import DeckScoreView

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


class CostView(ApiModel):
    """What a deck asks of a collection, in the only currency the app can see.

    ``short`` is what the player would have to acquire; ``composition`` is the deck's
    whole rarity makeup, which stands on its own with no collection recorded at all --
    the case that matters on the release day of a new set, when rarity is the only
    accessibility signal that exists yet.
    """
    short: dict[str, int]
    composition: dict[str, int]
    copies_short: int
    scarce_short: int
    affordable: bool
    #: One line, phrased server-side so two clients cannot word the bill differently.
    summary: str


class CoverageView(ApiModel):
    total_copies: int
    available_copies: int
    penalised_copies: int
    ratio: float
    complete: bool
    missing: list[dict[str, Any]]
    cost: CostView


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
    score: DeckScoreView | None = None


class DeckView(ApiModel):
    deck_id: str
    deck: dict[str, Any]
    validation: ValidationView


class ChampionOptionView(ApiModel):
    """One champion a legend may nominate, with how the field has fared on it."""

    card_id: str
    name: str
    image_url: str
    decks: int
    share: float
    win_rate: float
    #: False when the sample cannot support a published rate. The score still stands --
    #: it falls back to presence -- but the client must not print a number we withheld.
    win_rate_shown: bool
    score: float
    summary: str


class SuggestionView(ApiModel):
    """One card worth considering, and why."""

    card_id: str
    name: str
    image_url: str
    copies: int
    reason: str


class FieldMatchView(ApiModel):
    """Nearest published card family, without pretending it is matchup data."""

    available: bool
    archetype_id: str
    name: str
    sample_decks: int
    tournament_decks: int
    similarity: float
    threshold: float
    chosen_cards: int
    matched_cards: int
    copy_changes: int
    reference_deck_id: str
    reference_deck_name: str
    summary: str


class BuildSuggestionsView(ApiModel):
    """Everything the builder can offer for the deck as it currently stands.

    One response rather than an endpoint per zone: the answers all depend on the same
    deck, and splitting them would let the champion list disagree with the card list
    about what is in it.
    """

    champions: list[ChampionOptionView]
    main: list[SuggestionView]
    battlefields: list[SuggestionView]
    #: Kept separate from main-deck affinity: these are cards comparable published
    #: lists actually held in reserve, not generic cards the legend happens to play.
    sideboard: list[SuggestionView]
    #: Card id to copies. Always offered, whatever else is missing.
    runes: dict[str, int]
    rune_reason: str
    field_match: FieldMatchView
    #: Recomputed from the current payload on every suggestion refresh.
    deck_score: DeckScoreView
