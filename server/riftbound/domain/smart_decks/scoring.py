"""Two numbers a player can compare decks with.

The wizard hands over decks from three different places — a published list, that list
repaired against a collection, and a build assembled from the collection alone — and
until now only the first had a score. `meta_scoring.score_deck` reads a deck's *pedigree*
(evidence tier, placement, recency), which a repaired deck does not have: the moment a
card is swapped it stops being the list that placed 3rd of 257, so its pedigree is a
claim about a deck the player is no longer holding.

So both scores here are computed from the deck's **contents** instead. How much of what
the field actually plays does this list contain? That works identically for a published
list, a repair and a from-scratch build, which is the only way two of them can sit side
by side and be compared honestly.

**Meta score** measures against the strongest deck in the format. It answers "is this a
good deck", and it is the number that stays comparable when a player switches legend.

**Champion score** measures against the strongest published deck *for that champion*, so
the best list for your champion is 100 by construction. It answers the question a player
in the middle of a build is actually asking — "how close is this to the best version of
the deck I am building?" — and it is the one the wizard uses to choose between two
repairs, because a repair competes with other builds of the same deck, never with the
format at large.

The two disagree in exactly the way that makes both worth showing. A fringe champion's
best list is 100 on the champion scale and may be 40 on the meta scale; a mediocre build
of a dominant champion can be the reverse. Collapsing them into one number would hide
whichever of those two facts the player needed.

Strength is play-rate-weighted mass over the main deck: every copy is worth how often the
field plays that card. It is the same quantity `smart_decks_harness` already scores decks
by, so the wizard's acceptance run and the number on screen cannot drift apart.

One strength function, two denominators -- and the play rate behind it is **format-wide**,
not per-legend. That matters: computed per legend, the strongest deck of a legend with a
single champion is simultaneously the best deck of its champion and the best deck the
scoreboard knows about, so both scores read 100 and the second one says nothing. Measured
against the whole field, a fringe champion's best list is 100 for its champion and may be
40 in the format, which is the disagreement that makes showing two numbers worth doing.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from ..deck import Deck
from ..meta import MetaDeck

#: Shown to a player when there is nothing to measure against — a champion with no
#: published lists at all. Reported as "not scored" rather than as a zero, because a
#: champion nobody has published is not a champion that scores badly.
UNSCORED = -1.0


@dataclass(frozen=True)
class DeckScore:
    """One deck's standing, on both scales."""
    #: 0-100 against the strongest deck in the format. -1 when the format is empty.
    meta: float
    #: 0-100 against the strongest published deck for this champion, which is 100 by
    #: construction. -1 when that champion has no published lists.
    champion: float
    #: Raw play-rate mass, kept so a caller can compare two decks without re-deriving it
    #: and so a test can show the normalisation is the only difference between the two.
    strength: float

    @property
    def scored(self) -> bool:
        return self.champion > UNSCORED

    def describe(self) -> str:
        if not self.scored:
            return "Not scored — no published lists for this champion yet"
        return f"{self.champion:.0f} of 100 for this champion · {self.meta:.0f} in the format"


def strength_of(deck: Deck, play_rate: Mapping[str, float]) -> float:
    """How much of what the field plays this deck contains.

    Copies count: three of a staple is three times the commitment of one, and a deck that
    runs the whole package should not score the same as one that splashes it.
    """
    return sum(play_rate.get(card_id, 0.0) * copies for card_id, copies in deck.main.items())


@dataclass(frozen=True)
class Scoreboard:
    """The two baselines a deck is measured against, computed once per session.

    Built from the meta rather than passed around loose so the denominators cannot
    disagree between the deck on screen and the repairs underneath it -- which would
    show a repair scoring higher than the list it was repaired from.
    """
    play_rate: Mapping[str, float]
    best_format: float
    best_champion: Mapping[str, float]

    def score(self, deck: Deck) -> DeckScore:
        strength = strength_of(deck, self.play_rate)
        best = self.best_champion.get(deck.champion_id, 0.0)
        return DeckScore(
            meta=_ratio(strength, self.best_format),
            champion=_ratio(strength, best),
            strength=strength,
        )


def _ratio(strength: float, best: float) -> float:
    if best <= 0:
        return UNSCORED
    # Capped at 100: a repair can in principle out-mass every published list by loading
    # up on staples, and "112 of 100" reads as a bug rather than as a compliment.
    return min(100.0, 100.0 * strength / best)


def format_play_rate(decks: Sequence[MetaDeck]) -> dict[str, float]:
    """Share of the published field playing each card, across every legend.

    Unweighted by deck score, unlike the per-legend rate in ``legend_index``: this is the
    denominator for "how mainstream is this list", and weighting it by pedigree would
    fold a second, invisible judgement into a number presented as a simple share.
    """
    total = 0
    seen: dict[str, int] = {}
    for deck in decks:
        if not deck.deck.main:
            continue
        total += 1
        for card_id in deck.deck.main:
            seen[card_id] = seen.get(card_id, 0) + 1
    if not total:
        return {}
    return {card_id: count / total for card_id, count in seen.items()}


def build_scoreboard(
    decks: Iterable[MetaDeck], play_rate: Mapping[str, float]
) -> Scoreboard:
    """Baselines from the published field: the best deck overall, and per champion."""
    best_format = 0.0
    best_champion: dict[str, float] = {}
    for deck in decks:
        strength = strength_of(deck.deck, play_rate)
        best_format = max(best_format, strength)
        champion = deck.deck.champion_id
        if strength > best_champion.get(champion, 0.0):
            best_champion[champion] = strength
    return Scoreboard(
        play_rate=play_rate, best_format=best_format, best_champion=best_champion
    )


def better(left: DeckScore | None, right: DeckScore | None) -> bool:
    """Is ``left`` the one to hand over?

    Compared on the **champion** scale, which is the whole reason that scale exists. A
    repair is competing with other ways of building the same deck, not with the format --
    measuring it against the format's best would let a swap that is clearly right for a
    fringe champion lose to one that is clearly wrong, on the strength of a denominator
    neither deck can influence.

    Falls back to raw strength when neither has a champion baseline, so two unscored
    decks still order deterministically rather than by argument position.
    """
    if right is None:
        return left is not None
    if left is None:
        return False
    if left.scored != right.scored:
        return left.scored
    if left.champion != right.champion:
        return left.champion > right.champion
    return left.strength > right.strength


def choose(options: Sequence[tuple[str, Deck | None]], board: Scoreboard) -> str:
    """Which of several candidate decks to hand over. Returns the winning label."""
    best_label = ""
    best_score: DeckScore | None = None
    for label, deck in options:
        if deck is None:
            continue
        score = board.score(deck)
        if better(score, best_score):
            best_label, best_score = label, score
    return best_label
