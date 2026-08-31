"""Two numbers a player can compare decks with.

The wizard hands over decks from three places — a published list, that list repaired
against a collection, and a build from the collection alone — and only the first has a
pedigree. `meta_scoring.score_deck` reads evidence tier, placement and recency, which a
repair does not have: the moment a card is swapped it stops being the list that placed
3rd of 257, so its pedigree describes a deck the player is no longer holding.

So a deck is scored by **what real list it resembles, discounted by how much of that list
it actually contains**:

    affinity(deck) = max over published R of [ meta_score(R) × coverage(deck, R) ]

where coverage is the share of R's forty copies the deck has. Two properties fall out,
and the first one is why this module was rewritten:

**A repair can never out-score the list it repaired.** Coverage is bounded by 1, so the
best a deck can do is *be* the reference. That is the honest constraint: if substituting
a card you own for one you lack made the deck stronger, the published list would have
played your card. The first version of this module got this backwards — it scored a deck
by summing the format-wide play rate of its cards, which meant swapping any card for a
more-played one always raised the number. A repair does precisely that by construction,
so every repair scored at or above the deck it came from, and the wizard cheerfully
reported a compromise as an improvement.

**A thin champion cannot be cleared by accident.** The same first version divided by the
best play-rate mass among that champion's decks, which for a champion with one published
list was a trivially low bar — a repair hit 100 immediately. The legend-relative scale
now includes every champion paired with that legend, and coverage is measured against
a real complete list, so an obscure pairing does not manufacture its own easy ceiling.

The two scores differ only in which references they are allowed to look at.

**Meta score** ranges over the whole format, so it answers "is this a good deck". A deck
is only ever compared against lists for its own legend — domain identity means the others
have nothing in common with it — but the denominator is the format's best, so a fringe
legend's best deck reads honestly low.

**Legend score** ranges over every published list for that deck's legend, and the
denominator is the best of those, so the strongest evidenced list for a legend is 100
*by construction*. It answers how strong this build is among all known ways to build
that legend, without letting a thin champion create an artificially easy 100.

The two disagree in the way that makes both worth showing. The best evidenced build of
a fringe legend is 100 on its legend scale and may be 40 on the meta scale; collapsing
them would hide whichever fact the player needed.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from ..deck import Deck
from ..meta import MetaDeck

#: Shown when there is nothing to measure against — a legend with no published lists at
#: all. Reported as "not scored" rather than as a zero: unknown is not weak.
UNSCORED = -1.0


@dataclass(frozen=True)
class Reference:
    """One published list, and how much the meta thinks of it."""
    deck_id: str
    main: Mapping[str, int]
    copies: int
    score: float


@dataclass(frozen=True)
class DeckScore:
    """One deck's standing, on both scales."""
    #: 0-100 against the strongest deck in the format.
    meta: float
    #: 0-100 against the strongest published list for this legend.
    legend: float
    #: Share of the closest published list for this legend that this deck contains.
    #: Carried so a caller can say *why* a repair scored lower without re-deriving it.
    coverage: float

    @property
    def scored(self) -> bool:
        return self.legend > UNSCORED

    def describe(self) -> str:
        if not self.scored:
            return "Not scored — no published lists for this legend yet"
        return f"{self.meta:.0f} of 100 in the meta · {self.legend:.0f} for this legend"

    @property
    def disclaimer(self) -> str:
        return (
            "Directional estimate, not a prediction: published lists and results are "
            "incomplete, and player skill and matchups are not measured."
        )


def coverage_of(deck: Deck, reference: Reference) -> float:
    """The share of a reference list's copies this deck actually contains.

    Capped per card, so three copies of a staple cannot make up for a missing package:
    a deck holding six Defy against a list that runs three is not 200% of that slot.
    """
    if reference.copies <= 0:
        return 0.0
    held_counts = dict(deck.main)
    for card_id in deck.battlefields:
        held_counts[card_id] = held_counts.get(card_id, 0) + 1
    held = sum(min(held_counts.get(card_id, 0), n) for card_id, n in reference.main.items())
    return held / reference.copies


@dataclass(frozen=True)
class Scoreboard:
    """Published lists to measure against, and the two denominators.

    Grouped once per session so the deck on screen and the repairs beneath it cannot be
    scored against different populations -- which is how a repair ends up appearing to
    beat the list it was repaired from.
    """
    by_legend: Mapping[str, Sequence[Reference]] = field(default_factory=dict)
    best_format: float = 0.0
    best_legend: Mapping[str, float] = field(default_factory=dict)

    def score(self, deck: Deck) -> DeckScore:
        legend_refs = self.by_legend.get(deck.legend_id, ())
        legend_best = self.best_legend.get(deck.legend_id, 0.0)

        affinity, coverage = _affinity(deck, legend_refs)
        return DeckScore(
            meta=_ratio(affinity, self.best_format),
            legend=_ratio(affinity, legend_best),
            coverage=coverage,
        )


def _affinity(deck: Deck, references: Sequence[Reference]) -> tuple[float, float]:
    """The strongest published list this deck resembles, discounted by how much of it it
    has. Returns ``(affinity, coverage of the winning reference)``."""
    best = 0.0
    best_coverage = 0.0
    for reference in references:
        covered = coverage_of(deck, reference)
        value = reference.score * covered
        if value > best:
            best, best_coverage = value, covered
    return best, best_coverage


def _ratio(affinity: float, best: float) -> float:
    if best <= 0:
        return UNSCORED
    return min(100.0, 100.0 * affinity / best)


def build_scoreboard(
    decks: Iterable[MetaDeck], scores: Mapping[str, float]
) -> Scoreboard:
    """References and denominators from the published field.

    ``scores`` is the meta score per deck id, as ``meta_scoring.totals`` produces it --
    so the pedigree a published list already has is what weights it here, rather than a
    second opinion invented for this module.
    """
    by_legend: dict[str, list[Reference]] = {}
    best_format = 0.0
    best_legend: dict[str, float] = {}

    for deck in decks:
        if not deck.deck.main:
            continue
        score = scores.get(deck.deck_id, 0.0)
        measured = dict(deck.deck.main)
        for card_id in deck.deck.battlefields:
            measured[card_id] = measured.get(card_id, 0) + 1
        reference = Reference(
            deck_id=deck.deck_id,
            main=measured,
            copies=sum(measured.values()),
            score=score,
        )
        by_legend.setdefault(deck.deck.legend_id, []).append(reference)
        best_format = max(best_format, score)
        legend = deck.deck.legend_id
        if score > best_legend.get(legend, 0.0):
            best_legend[legend] = score

    return Scoreboard(
        by_legend=by_legend,
        best_format=best_format,
        best_legend=best_legend,
    )


def better(left: DeckScore | None, right: DeckScore | None) -> bool:
    """Is ``left`` the one to hand over?

    Compared on the **legend** scale, which is the whole reason that scale exists. A
    repair competes with other ways of building the same legend, not with the format --
    measuring it against the format's best would let a swap that is clearly right for a
    fringe champion lose on a denominator neither deck can influence.

    Falls back to coverage when neither has a legend baseline, so two unscored decks
    still order deterministically rather than by argument position.
    """
    if right is None:
        return left is not None
    if left is None:
        return False
    if left.scored != right.scored:
        return left.scored
    if left.legend != right.legend:
        return left.legend > right.legend
    return left.coverage > right.coverage


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
