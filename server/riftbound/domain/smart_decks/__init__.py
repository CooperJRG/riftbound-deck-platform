"""Smart Decks: find the best deck a collection can actually build.

The acceptance criterion is the whole design: *so long as the player owns the cards to
make a legal deck with that legend, that minimum will be found after a couple of
rounds*. Selection alone cannot satisfy it -- a published deck is an exact forty-card
list -- so construction sits underneath, and the session exists to learn just enough
about a collection to drive it.

Three modules, split where the reasoning changes:

* :mod:`knowledge` -- what we know and how sure we are. "I have all six" is a lower
  bound, not a count, and conflating the two is the bug that told a player holding
  twelve runes they were one short.
* :mod:`repair` -- filling a deck's holes from what they own, as two clearly labelled
  products: close to the original, or best from the collection.
* :mod:`engine` -- the session itself: the floor we can already promise, and what to ask
  next.

Everything the rest of the app imported from the single module is re-exported here, so
this split changed no call sites.
"""

from .engine import (
    MAX_PROPOSALS,
    PHASE_CHECKLIST,
    PHASE_DONE,
    PHASE_PROPOSE,
    W_COHERENCE,
    W_INFORMATION,
    W_PLAUSIBILITY,
    W_QUALITY,
    Engine,
    Proposal,
    Question,
    Run,
    Session,
    run_to_completion,
)
from .knowledge import (
    Gap,
    Knowledge,
    deck_requirements,
    gaps_for,
    unknown_cards,
)
from .repair import (
    REPAIRABLE_COPIES,
    Repair,
    Swap,
    repair,
)

__all__ = [
    "MAX_PROPOSALS",
    "PHASE_CHECKLIST",
    "PHASE_DONE",
    "PHASE_PROPOSE",
    "REPAIRABLE_COPIES",
    "W_COHERENCE",
    "W_INFORMATION",
    "W_PLAUSIBILITY",
    "W_QUALITY",
    "Engine",
    "Gap",
    "Knowledge",
    "Proposal",
    "Question",
    "Repair",
    "Run",
    "Session",
    "Swap",
    "deck_requirements",
    "gaps_for",
    "repair",
    "run_to_completion",
    "unknown_cards",
]
