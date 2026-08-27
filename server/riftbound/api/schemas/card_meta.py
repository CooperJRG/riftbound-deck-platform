"""Card-level meta tracking.

Separate from `meta` for the reason the domain keeps them apart: a champion's share
partitions the field and a card's adoption does not, and a shared module invites a
shared label.
"""

from __future__ import annotations

from .base import ApiModel
from .meta import TrendDeckView

# -- card meta ----------------------------------------------------------------


class CardPointView(ApiModel):
    period: str
    decks: int
    total_decks: int
    #: Decks playing this card over lists published in the interval. NOT a share of the
    #: metagame: a list plays forty cards, so these do not sum to 1.
    adoption: float
    charted: bool


class CardTrendView(ApiModel):
    card_id: str
    name: str
    image_url: str
    card_type: str
    rarity: str
    cost: int | None
    domains: list[str]
    decks: int
    adoption: float
    average_copies: float
    event_count: int
    momentum: float | None
    confidence: str
    points: list[CardPointView]


class CardTrendOverviewView(ApiModel):
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
    series: list[CardTrendView]


class CardHomeView(ApiModel):
    entity_id: str
    name: str
    image_url: str
    decks: int
    share_of_card: float


class CardPartnerView(ApiModel):
    """A card played alongside this one.

    The same pairing signal the deck builder fills from, shown rather than only used.
    """
    card_id: str
    name: str
    image_url: str
    together: int
    together_rate: float
    lift: float


class CardDetailView(ApiModel):
    trend: CardTrendView
    #: (copies, decks) pairs. A card played as a one-of is a different card to one
    #: played as a three-of, and the average hides that.
    copies_split: list[list[int]]
    legends: list[CardHomeView]
    champions: list[CardHomeView]
    partners: list[CardPartnerView]
    recent_decks: list[TrendDeckView]
