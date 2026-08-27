"""The deck-building wizard's request and response shapes."""

from __future__ import annotations

from typing import Any

from .base import ApiModel, StrictRequest
from .meta import MetaDeckView

# -- smart decks --------------------------------------------------------------


class LegendChoiceView(ApiModel):
    """A legend the wizard can build for, with what the meta knows about it."""
    legend_id: str
    name: str
    domains: list[str]
    image_url: str
    deck_count: int
    tournament_deck_count: int
    best_score: float
    #: Fraction of the legend's most-played cards the user already has. Advisory only:
    #: a low number is a hint, never a bar, because the point of the wizard is to find
    #: out what they can build rather than to guess in advance.
    familiarity: float
    #: The format era whose lists this legend's deck would be built from. Normally the
    #: current one. `"all"` means the era has no lists for it at all and the build falls
    #: back to the whole archive — a legal deck, but assembled from a format that may no
    #: longer be played, which the player is entitled to see rather than infer.
    era_id: str = ""


class RequirementRowView(ApiModel):
    """One row of the review screen: `Need 3 - You have [0][1][2][3]`."""
    card_id: str
    name: str
    zone: str
    needed: int
    image_url: str
    rarity: str
    #: What we already believe, so the row can be pre-filled and collapsed.
    known: bool
    exact: bool
    have: int


class SwapView(ApiModel):
    out_card_id: str
    out_name: str
    in_card_id: str
    in_name: str
    copies: int
    reason: str


class RepairDeckCardView(ApiModel):
    """One card of the finished deck, named so it can actually be shown."""
    card_id: str
    name: str
    image_url: str
    zone: str
    copies: int
    #: True for a card the repair brought in. A swap that names a card the player cannot
    #: find anywhere on the page reads as the wizard talking about a deck it will not
    #: show them.
    added: bool


class DeckScoreView(ApiModel):
    """How strong a deck is, on the two scales a player can act on.

    Both measure the same thing -- how much of what the field plays this list contains --
    and differ only in what they are measured against. `meta` compares it to the
    strongest deck in the format; `champion` compares it to the strongest published list
    for its champion, which is 100 by construction.

    `-1` on either means there was nothing to measure against, and must be rendered as
    "not scored" rather than as a zero: a champion nobody has published is not a champion
    that scores badly.
    """
    meta: float
    champion: float
    #: Share of the closest published list for this champion that this deck contains.
    #: Why a repair scored lower, without the client re-deriving it.
    coverage: float
    scored: bool
    #: One line, phrased server-side so two clients cannot describe it differently.
    summary: str


class RepairView(ApiModel):
    kind: str               # 'none' | 'conservative' | 'free'
    drift: int              # copies changed
    swaps: list[SwapView]
    deck: dict[str, Any]
    #: The finished list, resolved to names and art.
    cards: list[RepairDeckCardView]
    legal: bool
    score: DeckScoreView | None = None


class GapView(ApiModel):
    card_id: str
    name: str
    needed: int
    have: int
    short: int


class FloorView(ApiModel):
    """The best deck we can already promise. The banner reads from this."""
    deck: dict[str, Any]
    quality: float
    summary: str
    score: DeckScoreView | None = None
    #: The finished list, named and illustrated. The finish screen shows the deck a
    #: player is being handed; a payload of card ids is not a deck they can look at.
    cards: list[RepairDeckCardView] = []


class QuestionView(ApiModel):
    reason: str
    cards: list[RequirementRowView]


class BanNoticeView(ApiModel):
    """A ban worth telling the player about.

    Reported rather than enforced wherever we can, because we do not know which format
    they are playing. `enforced` says whether our profile actually acted on it.
    """
    card_id: str
    name: str
    source: str        # 'profile' | 'upstream'
    enforced: bool
    in_deck: bool
    message: str


class ProposalView(ApiModel):
    """Everything the review screen needs for one round."""
    phase: str
    reason: str
    round: int
    #: The deck being shown, when there is one.
    deck: MetaDeckView | None = None
    requirements: list[RequirementRowView] = []
    gaps: list[GapView] = []
    conservative: RepairView | None = None
    free: RepairView | None = None
    #: Which repair the wizard picked: 'conservative', 'free', or '' when neither was
    #: needed. The client renders that one rather than offering the choice — but still
    #: labels which kind it is, because choosing for someone is not the same as not
    #: telling them what they are holding.
    chosen: str = ""
    #: Score of the deck being shown, on both scales.
    deck_score: DeckScoreView | None = None
    question: QuestionView | None = None
    floor: FloorView | None = None
    #: Plain-English state of play, e.g. "Short by 3 more main."
    feasibility: str = ""
    can_build: bool = False
    #: Ban warnings for the deck on screen and the deck we would hand over.
    ban_notices: list[BanNoticeView] = []


class DeclinedCardView(ApiModel):
    """A card ruled out by preference, so the UI can show it and offer it back."""
    card_id: str
    name: str
    image_url: str


class SmartSessionView(ApiModel):
    session_id: str
    legend_id: str
    legend_name: str
    phase: str
    rounds: int
    known_cards: int
    saved_deck_id: str
    created_at: str
    updated_at: str
    proposal: ProposalView | None = None
    #: Cards the player has ruled out by preference. Shown so a decline is visible and
    #: reversible rather than a thing the deck silently stopped containing.
    declined: list[DeclinedCardView] = []


class StartSessionRequest(StrictRequest):
    legend_id: str


class AnswerRequest(StrictRequest):
    """One answered round.

    ``deck_id`` names the deck that was on screen; omit it for a checklist answer, in
    which case ``asked`` must list every card the question covered. The distinction
    matters: an unticked card on a checklist means "I own none", while a card simply
    absent from a deck answer means "I have what it asked for".
    """
    deck_id: str = ""
    have: dict[str, int] = {}
    asked: list[str] = []


class DeclineRequest(StrictRequest):
    """Cards the player does not want to play.

    The whole set, not a delta: taking a decline back is then the same call as adding
    one, and the client never has to send a difference it might compute wrongly.
    """
    card_ids: list[str] = []


class AcceptRequest(StrictRequest):
    """Copy a deck out of the wizard into the library."""
    name: str = ""
    #: 'floor' | 'conservative' | 'free' -- which of the offered decks to keep.
    which: str = "floor"


class SaveCollectionRequest(StrictRequest):
    """Opt-in write-back of what the session learned.

    ``exact_only`` defaults true: a lower bound ("I have at least the 6 this deck
    wants") is not a collection count, and writing it as one would understate a player
    who owns twelve.
    """
    exact_only: bool = True


class SaveCollectionResult(ApiModel):
    #: Cards recorded as owned. Counts only positive quantities, because "I wrote 14
    #: cards" reading back as an empty collection is the kind of lie that costs trust.
    cards_written: int
    copies_written: int
    #: Cards the session established they own none of. Recorded as a real answer, and
    #: reported separately because clearing an entry is not the same as adding one.
    cards_cleared: int
    skipped_lower_bounds: int
