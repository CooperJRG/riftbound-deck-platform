"""Does Smart Decks actually meet its acceptance criterion?

An acceptance criterion that isn't measured is a hope. This drives whole sessions against
synthetic players, answering each round truthfully from a collection the harness knows and
the engine doesn't, and reports four numbers:

===========================  =========================================================
metric                       target
===========================  =========================================================
``solved_when_feasible``     **1.0** — if a legal deck exists we must find one. Phase 3
                             makes this a guarantee, so anything less is a bug.
``false_negatives``          **0** — we said "can't build" when they could. The worst
                             failure available, because the player is told no while
                             holding a yes.
``rounds_to_answer``         median <= 3, p90 <= 5
``quality_gap``              how far the deck we found sits below the best the
                             collection could theoretically support
===========================  =========================================================

The reference point for why this file exists: v2 shipped an equivalent feature whose own
evaluation recorded ``strictBuildableEmptyResultRate: 0.814`` — asked for a deck from a
collection it returned nothing four times in five, and nobody noticed because nothing
measured it.
"""

from __future__ import annotations

import random
import statistics
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from .cards import Catalog
from .deck_builder import assess, build
from .legend_index import LegendIndex
from .meta import MetaDeck
from .rules import BoundRules
from .smart_decks import Engine, run_to_completion

#: Targets for what a session costs the player, in decisions rather than screens.
#:
#: Measured on the code that introduced them, so they are honest about where we start:
#: cards to answer is already median 45 / p90 71, and the sweep is what breaks the rest
#: -- cost of a "no" is median 290, and the worst single screen p90 232 against a
#: ``MAX_CHECKLIST`` of 60 that the sweep path never consults.
#:
#: The two populations are separated on purpose. A player who *can* build should reach a
#: deck cheaply; a player who cannot should be told so cheaply, and that second number
#: is the one no metric here used to cover.
TARGET_CARDS_TO_ANSWER = 40
TARGET_P90_CARDS_TO_ANSWER = 80
#: Being told "no" should cost less than being told yes: there is nothing to show for it.
TARGET_CARDS_TO_NO = 60
TARGET_P90_CARDS_TO_NO = 120
#: One screen, at the size the engine already says a checklist should be.
TARGET_P90_LARGEST_ROUND = 60

#: How likely a player owns a card of each rarity, for generated collections.
OWNERSHIP_BY_RARITY = {
    "Common": 0.92, "Uncommon": 0.78, "Rare": 0.5, "Epic": 0.28, "Showcase": 0.08,
}
DEFAULT_OWNERSHIP = 0.4


@dataclass(frozen=True)
class Player:
    """A synthetic collection, and where it came from."""
    name: str
    owned: Mapping[str, int]


@dataclass(frozen=True)
class Outcome:
    """What happened when one player ran the wizard for one legend."""
    player: str
    legend_id: str
    feasible: bool          # a legal deck genuinely exists in their collection
    solved: bool            # the wizard produced one
    rounds: int             # questions asked in total
    rounds_to_answer: int   # questions before the first buildable deck appeared
    cards_asked: int        # decisions the session asked for, start to finish
    cards_to_answer: int | None   # ...before the first buildable deck; None if never
    largest_round: int      # worst single screen
    found_score: float      # meta play-rate mass of the deck we found
    best_score: float       # ...of the best deck the collection could support

    @property
    def false_negative(self) -> bool:
        return self.feasible and not self.solved

    @property
    def quality_gap(self) -> float:
        if not self.solved or self.best_score <= 0:
            return 0.0
        return max(0.0, (self.best_score - self.found_score) / self.best_score)


@dataclass(frozen=True)
class Report:
    outcomes: tuple[Outcome, ...]

    @property
    def feasible(self) -> tuple[Outcome, ...]:
        return tuple(o for o in self.outcomes if o.feasible)

    @property
    def solved_when_feasible(self) -> float:
        pool = self.feasible
        return sum(1 for o in pool if o.solved) / len(pool) if pool else 1.0

    @property
    def false_negatives(self) -> int:
        return sum(1 for o in self.outcomes if o.false_negative)

    @property
    def rounds(self) -> list[int]:
        """Questions until the player could be shown something buildable."""
        return sorted(o.rounds_to_answer for o in self.feasible if o.solved)

    def percentile(self, values: Sequence[float], fraction: float) -> float:
        if not values:
            return 0.0
        index = min(len(values) - 1, int(len(values) * fraction))
        return sorted(values)[index]

    @property
    def median_rounds(self) -> float:
        return statistics.median(self.rounds) if self.rounds else 0.0

    @property
    def p90_rounds(self) -> float:
        return self.percentile(self.rounds, 0.9)

    @property
    def median_total_rounds(self) -> float:
        totals = [o.rounds for o in self.feasible if o.solved]
        return statistics.median(totals) if totals else 0.0

    @property
    def median_quality_gap(self) -> float:
        gaps = [o.quality_gap for o in self.feasible if o.solved]
        return statistics.median(gaps) if gaps else 0.0

    # -- what the session costs the player ------------------------------------
    #
    # Rounds are screens; cards are decisions. The two came apart once the closing
    # question learned to sweep the remaining pool, and every metric above counts
    # screens -- so a session could report two rounds while asking for hundreds of
    # decisions and still pass. These count decisions instead.

    @property
    def cards_to_answer(self) -> list[int]:
        """Decisions made before a deck appeared, for players who got one."""
        return sorted(
            o.cards_to_answer
            for o in self.feasible
            if o.solved and o.cards_to_answer is not None
        )

    @property
    def infeasible(self) -> tuple[Outcome, ...]:
        """Players who genuinely cannot build this legend.

        Every metric above is computed over ``feasible`` only, which left the larger
        population -- the ones who are told "no" -- outside all of them. The cost of
        reaching that "no" is the thing this harness was blindest to.
        """
        return tuple(o for o in self.outcomes if not o.feasible)

    @property
    def cards_to_no(self) -> list[int]:
        """Decisions spent by a player who ends up with nothing."""
        return sorted(o.cards_asked for o in self.infeasible)

    @property
    def largest_rounds(self) -> list[int]:
        """The worst single screen in each session, across everybody."""
        return sorted(o.largest_round for o in self.outcomes)

    @property
    def median_cards_to_answer(self) -> float:
        return statistics.median(self.cards_to_answer) if self.cards_to_answer else 0.0

    @property
    def p90_cards_to_answer(self) -> float:
        return self.percentile(self.cards_to_answer, 0.9)

    @property
    def median_cards_to_no(self) -> float:
        return statistics.median(self.cards_to_no) if self.cards_to_no else 0.0

    @property
    def p90_cards_to_no(self) -> float:
        return self.percentile(self.cards_to_no, 0.9)

    @property
    def p90_largest_round(self) -> float:
        return self.percentile(self.largest_rounds, 0.9)

    def render(self) -> str:
        lines = [
            f"players x legends run   {len(self.outcomes)}",
            f"  of which feasible     {len(self.feasible)}",
            f"solved when feasible    {self.solved_when_feasible:.1%}   (target 100%)",
            f"false negatives         {self.false_negatives}            (target 0)",
            f"rounds to answer        median {self.median_rounds:.0f}, p90 {self.p90_rounds:.0f}"
            f"   (target <=3, <=5)",
            f"rounds to session end   median {self.median_total_rounds:.0f}",
            f"quality gap             median {self.median_quality_gap:.1%}  (target <=10%)",
            "",
            f"  of which infeasible   {len(self.infeasible)}",
            f"cards to answer         median {self.median_cards_to_answer:.0f}, "
            f"p90 {self.p90_cards_to_answer:.0f}"
            f"   (target <={TARGET_CARDS_TO_ANSWER}, <={TARGET_P90_CARDS_TO_ANSWER})",
            f'cards to a "no"         median {self.median_cards_to_no:.0f}, '
            f"p90 {self.p90_cards_to_no:.0f}"
            f"   (target <={TARGET_CARDS_TO_NO}, <={TARGET_P90_CARDS_TO_NO})",
            f"largest single round    p90 {self.p90_largest_round:.0f}"
            f"          (target <={TARGET_P90_LARGEST_ROUND})",
        ]
        if not self.card_targets_met:
            lines.append("")
            lines.append("NOTE  card targets are reported, not enforced -- see phase 1.")
        return "\n".join(lines)

    @property
    def card_targets_met(self) -> bool:
        """Do the per-decision costs clear their targets?

        Deliberately *not* part of :attr:`passes` yet. These targets fail on the code
        that introduced them -- that is the finding, not a regression -- and wiring a
        known-failing gate into the release check would only teach everyone to ignore
        the check. Phase 1 changes the closing question so these can pass; fold this
        into ``passes`` in the same commit that makes it true.
        """
        return (
            self.median_cards_to_answer <= TARGET_CARDS_TO_ANSWER
            and self.p90_cards_to_answer <= TARGET_P90_CARDS_TO_ANSWER
            and self.median_cards_to_no <= TARGET_CARDS_TO_NO
            and self.p90_cards_to_no <= TARGET_P90_CARDS_TO_NO
            and self.p90_largest_round <= TARGET_P90_LARGEST_ROUND
        )

    @property
    def passes(self) -> bool:
        return (
            self.solved_when_feasible >= 1.0
            and self.false_negatives == 0
            and self.median_rounds <= 3
            and self.p90_rounds <= 5
        )


# -- synthetic players --------------------------------------------------------


def random_collection(
    catalog: Catalog, *, rng: random.Random, scale: float = 1.0, copies: int = 3
) -> dict[str, int]:
    """A collection sampled by rarity.

    ``scale`` shifts the whole distribution: 0.3 is somebody who has opened a few packs,
    1.0 a committed player. Rarity-weighted because that is how collections actually
    look, and it is what makes the hard cases hard.
    """
    owned: dict[str, int] = {}
    for card in catalog:
        chance = OWNERSHIP_BY_RARITY.get(card.rarity, DEFAULT_OWNERSHIP) * scale
        held = sum(1 for _ in range(copies) if rng.random() < chance)
        if card.card_type == "Rune" and held:
            held = rng.choice([6, 9, 12])  # runes come in bulk or not at all
        if held:
            owned[card.card_id] = held
    return owned


def collection_from_decks(
    decks: Sequence[MetaDeck], *, rng: random.Random, noise: float = 0.15
) -> dict[str, int]:
    """A collection built around real decks, then perturbed.

    Closer to a real player than pure sampling: people own the cards for the decks they
    play. The noise removes a fraction, which is exactly the "missing one of a three-of"
    case the wizard exists to handle.
    """
    owned: dict[str, int] = {}
    for deck in decks:
        for card_id, copies in deck.deck.main.items():
            owned[card_id] = max(owned.get(card_id, 0), copies)
        for card_id, copies in deck.deck.runes.items():
            owned[card_id] = max(owned.get(card_id, 0), copies)
        for card_id in deck.deck.battlefields:
            owned[card_id] = max(owned.get(card_id, 0), 1)
        if deck.deck.legend_id:
            owned[deck.deck.legend_id] = max(owned.get(deck.deck.legend_id, 0), 1)
    for card_id in list(owned):
        if rng.random() < noise:
            owned[card_id] = max(0, owned[card_id] - rng.randint(1, 2))
            if owned[card_id] == 0:
                del owned[card_id]
    return owned


# -- running ------------------------------------------------------------------


def _deck_quality(deck, profile) -> float:
    """How much of the meta's preferred cards a deck actually contains."""
    if deck is None:
        return 0.0
    return sum(profile.play_rate.get(c, 0.0) * n for c, n in deck.main.items())


def run_one(
    player: Player,
    legend_id: str,
    *,
    engine: Engine,
    catalog: Catalog,
    rules: BoundRules,
) -> Outcome:
    """One player, one legend, start to finish."""
    truth = player.owned
    # Ground truth: could they build at all, and what is the best possible?
    feasible = assess(legend_id, truth, catalog=catalog, rules=rules).ok
    best = build(
        legend_id, truth, catalog=catalog, rules=rules,
        preference=engine.profile.preference(),
    )

    run = run_to_completion(engine, legend_id, truth)
    found = run.floor
    if found is None and run.proposal.conservative is not None:
        found = run.proposal.conservative.deck

    return Outcome(
        player=player.name,
        legend_id=legend_id,
        feasible=feasible,
        solved=found is not None,
        rounds=run.rounds,
        rounds_to_answer=run.rounds_to_answer if run.rounds_to_answer is not None else run.rounds,
        cards_asked=run.cards_asked,
        cards_to_answer=run.cards_to_answer,
        largest_round=run.largest_round,
        found_score=_deck_quality(found, engine.profile),
        best_score=_deck_quality(best, engine.profile),
    )


def simulate(
    *,
    catalog: Catalog,
    rules: BoundRules,
    index: LegendIndex,
    decks: Iterable[MetaDeck],
    scores: Mapping[str, float],
    legends: Sequence[str],
    players: Sequence[Player],
) -> Report:
    """Run every player against every legend."""
    by_legend: dict[str, dict[str, MetaDeck]] = {}
    for deck in decks:
        by_legend.setdefault(deck.deck.legend_id, {})[deck.deck_id] = deck

    outcomes: list[Outcome] = []
    for legend_id in legends:
        profile = index.get(legend_id)
        if profile is None:
            continue
        engine = Engine(
            catalog=catalog, rules=rules, profile=profile,
            decks=by_legend.get(legend_id, {}), scores=scores,
        )
        for player in players:
            outcomes.append(
                run_one(player, legend_id, engine=engine, catalog=catalog, rules=rules)
            )
    return Report(outcomes=tuple(outcomes))
