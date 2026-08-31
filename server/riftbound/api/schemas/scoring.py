"""Shared response shapes for competitive deck-strength estimates."""

from .base import ApiModel


class DeckScoreView(ApiModel):
    """How strong a deck is, on the two scales a player can act on.

    Both measure the same thing -- how much of what the field plays this list contains --
    and differ only in what they are measured against. ``meta`` compares it to the
    strongest deck in the format; ``legend`` compares it to the strongest published
    list for its legend, which is 100 by construction.

    ``-1`` on either means there was nothing to measure against, and must be rendered
    as "not scored" rather than as a zero: a legend with no published reference is
    unknown, not weak.
    """

    meta: float
    legend: float
    # Share of the closest published list for this legend that this deck contains.
    coverage: float
    scored: bool
    summary: str
    disclaimer: str
