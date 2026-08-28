"""Deck payloads, and what validation says about them.

Legality and coverage are separate fields on purpose: "this deck is illegal" and "this
deck is legal but you are missing four cards" are different problems with different
answers, and v2 conflated them.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from .base import ApiModel, StrictRequest

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


class DeckView(ApiModel):
    deck_id: str
    deck: dict[str, Any]
    validation: ValidationView
