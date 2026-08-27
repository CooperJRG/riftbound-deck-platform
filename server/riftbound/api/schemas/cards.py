"""Cards, printings, and a page of them."""

from __future__ import annotations

from pydantic import Field

from .base import ApiModel

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
