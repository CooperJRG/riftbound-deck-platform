"""The opening hand: what the odds are, and what a mulligan does to them.

Two things live here, and keeping them apart matters.

**The odds are computed, not simulated.** Drawing ``k`` copies of a card from a deck of
``N`` with ``K`` copies in it is a hypergeometric distribution with a closed form, and
Python has exact integer binomials. A Monte Carlo estimate of a number with an exact
answer is a worse number that also takes longer, and it makes the page disagree with
itself between reloads. The simulator deals real hands because watching a hand is the
point of a simulator; the percentages beside it are arithmetic.

**The rules come from the format profile, never from here.** Hand size, mulligan size
and the draw step are read out of ``data/rules/*.json`` like every other rule in this
codebase, so a format that does not record them gets no simulator rather than one
running on a guess. That is not pedantry: every number this module produces is a
function of the hand size, so inventing it would make all of them confidently wrong.

The mulligan is modelled exactly as the profile describes it -- up to
``mulligan_max`` cards to the **bottom** of the deck, drawing the same number back,
once. Bottoming rather than shuffling is what makes the replacement draw a clean
hypergeometric over the remaining deck: a recycled card cannot come back, so the
replacements are drawn from the ``N - hand`` cards that were never in hand.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from math import comb

from .cards import Catalog
from .deck import Deck
from .rules import BoundRules

#: A card has to appear in at least this share of opening hands before it is worth a
#: row of its own. Below it the table becomes forty lines of "3%", which is a list of
#: the deck rather than a reading of it.
NOTABLE_ODDS = 0.05


def hypergeometric(population: int, successes: int, draws: int, wanted: int) -> float:
    """P(exactly ``wanted`` successes) when drawing ``draws`` from ``population``."""
    if draws < 0 or population <= 0 or successes < 0 or wanted < 0:
        return 0.0
    if wanted > successes or wanted > draws:
        return 0.0
    if draws > population or successes > population:
        return 0.0
    total = comb(population, draws)
    if total == 0:
        return 0.0
    return comb(successes, wanted) * comb(population - successes, draws - wanted) / total


def at_least_one(population: int, successes: int, draws: int) -> float:
    """P(at least one success). The question a player actually asks about a card."""
    if successes <= 0 or draws <= 0 or population <= 0:
        return 0.0
    if draws >= population:
        return 1.0 if successes > 0 else 0.0
    return 1.0 - hypergeometric(population, successes, draws, 0)


def at_least_one_of_any(
    population: int, copies: Sequence[int], draws: int
) -> float:
    """P(at least one card from a group), given the copy count of each member.

    The complement of drawing none of them, which is why the group is collapsed to a
    single success count: "none of these" does not care which of them you missed. Doing
    it per card and adding would double-count every hand holding two of the group --
    the mistake that makes an "odds of a turn-one play" figure exceed 100%.
    """
    return at_least_one(population, sum(max(0, c) for c in copies), draws)


@dataclass(frozen=True)
class OpeningRules:
    """The gameplay values the simulator runs on, and where they came from."""

    hand_size: int
    mulligan_max: int
    #: "bottom" or "shuffle". Only "bottom" is implemented, because it is what the
    #: profile records; a profile saying otherwise is reported rather than assumed.
    mulligan_destination: str
    draw_per_turn: int
    #: False while these values are corroborated from published guides rather than read
    #: off the cited rulebook. Shown in the UI, exactly as the era boundary's is.
    cited: bool
    evidence: str

    @property
    def available(self) -> bool:
        """Whether this format records enough to simulate an opening hand at all."""
        return self.hand_size > 0


@dataclass(frozen=True)
class CardOdds:
    """How likely one card is to be in the opening hand."""

    card_id: str
    name: str
    image_url: str
    copies: int
    cost: int | None
    #: P(at least one copy) in the opening hand, before any mulligan.
    opening: float
    #: P(at least one copy) by the given turn, opening hand plus per-turn draws.
    by_turn_three: float

    def describe(self) -> str:
        return f"{self.opening:.0%} in your opening hand, {self.by_turn_three:.0%} by turn 3"


@dataclass(frozen=True)
class OpeningOdds:
    """What the deck's opening hand looks like, as arithmetic."""

    rules: OpeningRules
    deck_size: int
    #: P(the chosen champion is in the opening hand). Its own field because the
    #: champion is the one card the deck is built around.
    champion: CardOdds | None
    #: P(at least one card costing `<= n`) for a few early costs -- "can I do anything
    #: on turn one" as a number.
    playable_by_cost: tuple[tuple[int, float], ...]
    cards: tuple[CardOdds, ...]

    @property
    def available(self) -> bool:
        return self.rules.available and self.deck_size > 0


def opening_rules(rules: BoundRules, *, evidence: str = "", cited: bool = False) -> OpeningRules:
    """Read the gameplay values off a bound format profile.

    A format that records no hand size yields ``hand_size == 0``, which every caller
    reads as "this format cannot be simulated". Skirmish is deliberately in that state:
    its deck sizes differ from constructed's and nothing available says whether its
    opening hand does too, so it gets no simulator rather than constructed's numbers
    wearing its name.
    """
    return OpeningRules(
        hand_size=rules.int_constraint("opening_hand_size", 0),
        mulligan_max=rules.int_constraint("mulligan_max", 0),
        mulligan_destination=rules.str_constraint("mulligan_destination", "bottom"),
        draw_per_turn=rules.int_constraint("draw_per_turn", 0),
        cited=cited,
        evidence=evidence,
    )


def _seen_by_turn(rules: OpeningRules, turn: int) -> int:
    """Cards seen by the start of ``turn``: the opening hand plus one draw per turn.

    Turn one is the opening hand alone -- the draw step of your first turn is a draw, so
    by turn three you have seen the hand plus two further cards. Off-by-one here would
    quietly overstate every "by turn N" figure on the page.
    """
    if turn <= 1:
        return rules.hand_size
    return rules.hand_size + rules.draw_per_turn * (turn - 1)


def opening_odds(
    deck: Deck,
    *,
    rules: BoundRules,
    catalog: Catalog,
    evidence: str = "",
    cited: bool = False,
    costs: Iterable[int] = (1, 2, 3),
) -> OpeningOdds:
    """Exact opening-hand probabilities for a deck as it currently stands.

    Computed over the **main deck only**. Runes and battlefields are separate zones in
    this game and are never drawn, so folding them into the population would deflate
    every probability by a third -- the single easiest way to get this whole feature
    quietly wrong.
    """
    opening = opening_rules(rules, evidence=evidence, cited=cited)
    population = deck.main_total
    if not opening.available or population <= 0:
        return OpeningOdds(
            rules=opening, deck_size=population, champion=None,
            playable_by_cost=(), cards=(),
        )

    hand = min(opening.hand_size, population)
    by_three = min(_seen_by_turn(opening, 3), population)

    def odds_for(card_id: str, copies: int) -> CardOdds:
        card = catalog.get(card_id)
        return CardOdds(
            card_id=card_id,
            name=card.name if card else card_id,
            image_url=card.image_url if card else "",
            copies=copies,
            cost=card.cost if card else None,
            opening=at_least_one(population, copies, hand),
            by_turn_three=at_least_one(population, copies, by_three),
        )

    rows = [odds_for(card_id, copies) for card_id, copies in deck.main.items()]
    rows.sort(key=lambda row: (-row.opening, row.name))

    champion = None
    if deck.champion_id and deck.champion_id in deck.main:
        champion = odds_for(deck.champion_id, deck.main[deck.champion_id])

    # "Can I do anything early" as one number per cost, collapsing the group rather than
    # summing per card -- see `at_least_one_of_any`.
    playable: list[tuple[int, float]] = []
    for ceiling in costs:
        copies = [
            count
            for card_id, count in deck.main.items()
            if (c := catalog.get(card_id)) is not None
            and c.cost is not None
            and c.cost <= ceiling
        ]
        if copies:
            playable.append((ceiling, at_least_one_of_any(population, copies, hand)))

    return OpeningOdds(
        rules=opening,
        deck_size=population,
        champion=champion,
        playable_by_cost=tuple(playable),
        cards=tuple(row for row in rows if row.opening >= NOTABLE_ODDS),
    )


def mulligan_odds(
    population: int, successes: int, *, hand_size: int, recycled: int
) -> float:
    """P(holding at least one copy after a mulligan that digs for it.

    **This assumes a strategy, and the assumption is the whole meaning of the number.**
    A mulligan's outcome is not a property of the deck alone -- it depends on which
    cards the player sends away, which is a decision, not a distribution. The strategy
    modelled here is the only one the question implies: *you never bottom a copy of the
    card you are looking for*. So you end up holding one if it was already in your hand,
    or if a replacement draw finds one.

    Bottoming rather than shuffling is what makes the second half clean: the recycled
    cards go under the deck, so replacements come from the ``population - hand_size``
    cards that were never in hand, and a card you sent away cannot return.

        P = 1 - P(none in the opening hand) x P(none in the replacements | none in hand)

    Conditioning on a *specific* hand is what the simulator does by dealing one; this is
    the unconditional figure that belongs beside a deck list.
    """
    if hand_size <= 0 or population <= 0 or successes <= 0:
        return 0.0
    recycled = max(0, min(recycled, hand_size))
    miss_hand = hypergeometric(population, successes, hand_size, 0)
    if recycled == 0 or miss_hand == 0.0:
        return 1.0 - miss_hand
    # Given none were in hand, every copy is still among the cards never drawn.
    remaining = population - hand_size
    if remaining <= 0:
        return 1.0 - miss_hand
    miss_drawn = hypergeometric(remaining, successes, min(recycled, remaining), 0)
    return 1.0 - miss_hand * miss_drawn


def shuffled_deck(deck: Deck) -> list[str]:
    """The main deck as a flat list of card ids, one entry per copy.

    Not shuffled here: the caller owns the randomness, so a test can deal a known
    order and the client can shuffle in the browser without a round trip per hand.
    """
    out: list[str] = []
    for card_id, copies in deck.main.items():
        out.extend([card_id] * max(0, copies))
    return out


def hand_summary(hand: Mapping[str, int], catalog: Catalog) -> str:
    """One line describing a dealt hand, for the simulator's readout."""
    total = sum(hand.values())
    costs = [
        c.cost
        for card_id in hand
        if (c := catalog.get(card_id)) is not None and c.cost is not None
    ]
    if not costs:
        return f"{total} cards"
    return f"{total} cards · curve {min(costs)}–{max(costs)}"
