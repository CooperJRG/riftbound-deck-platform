"""The session: what to ask next, and what we can already promise.

Two tracks run every round. The **floor** is the best deck the collection definitely
supports, recomputed after every answer and never allowed to get worse -- it is what
lets somebody stop early and still leave with a deck. The **proposal** is what to put in
front of them next, chosen against how much it would teach us, how likely they are to
own it, and whether its archetype is one they can field at all.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace

from ..cards import Catalog
from ..deck import Deck
from ..deck_builder import (
    REQ_BATTLEFIELDS,
    REQ_CHAMPION,
    REQ_LEGEND,
    REQ_MAIN,
    REQ_RUNES,
    Feasibility,
    assess,
    build,
    legal_champions,
    legal_main_pool,
    legal_zone_pool,
)
from ..legend_index import LegendProfile
from ..meta import MetaDeck
from ..rules import BoundRules
from .knowledge import (
    Knowledge,
    _plural,
    deck_requirements,
    gaps_for,
    unknown_cards,
)
from .repair import REPAIRABLE_COPIES, Repair, repair

PHASE_PROPOSE = "propose"
PHASE_CHECKLIST = "checklist"
PHASE_DONE = "done"

#: How many decks to show before falling back to a direct checklist. Coverage measured
#: on the snapshot: 3-4 decks cover half a legend's card pool, and the curve flattens
#: after that, so a fifth proposal buys much less than simply asking.
MAX_PROPOSALS = 4


#: Weights for choosing the next deck to ask about.
W_QUALITY = 0.35
W_PLAUSIBILITY = 0.20
W_INFORMATION = 0.25
#: How much a deck's own archetype being fieldable counts.
#:
#: Without this the wizard will happily keep offering variants of a plan whose core the
#: player does not own, patching the same holes each time. A deck is not the sum of its
#: individually popular cards: if the enabler is missing, the expensive payoffs it was
#: buying time for are just expensive.
W_COHERENCE = 0.20

#: How much expected yield a checklist aims for, as a multiple of the shortfall. Above
#: 1 because the estimate is a prior, not a measurement, and a checklist that falls just
#: short costs a whole extra round.
CHECKLIST_MARGIN = 2.0

#: Answers needed before the observed ownership rate is trusted over the rarity priors,
#: and the shrinkage constant pulling small samples back toward them.
CALIBRATION_MIN = 25

#: However pessimistic a player's answers look, never assume they own nothing: that
#: would make every question the whole pool.
CALIBRATION_FLOOR = 0.15

#: After this many direct questions have failed to close the gap, ask the whole
#: remaining pool rather than another estimate.
SWEEP_AFTER = 1
MIN_CHECKLIST = 12
MAX_CHECKLIST = 60

#: Prior probability a player owns a card, by rarity, used only to rank questions.
#: Deliberately crude — it orders candidates, it never decides anything.
RARITY_PRIOR = {
    "Common": 0.85, "Uncommon": 0.7, "Rare": 0.45, "Epic": 0.25, "Showcase": 0.1,
}
DEFAULT_PRIOR = 0.4


# -- knowledge ----------------------------------------------------------------






# -- the session --------------------------------------------------------------


@dataclass(frozen=True)
class Session:
    """One run of the wizard. Immutable; each answer returns a new session."""
    legend_id: str
    knowledge: Knowledge = field(default_factory=Knowledge)
    asked: tuple[str, ...] = ()          # deck ids already shown
    phase: str = PHASE_PROPOSE
    checklists: int = 0                  # direct questions asked so far

    @property
    def rounds(self) -> int:
        return len(self.asked)



@dataclass(frozen=True)
class Question:
    """Cards to ask about directly, once decks have stopped being informative."""
    reason: str
    card_ids: tuple[str, ...]



@dataclass(frozen=True)
class Proposal:
    """What to show next, and what we can already promise."""
    phase: str
    deck: MetaDeck | None = None
    #: The proposed deck adjusted to what they own. Conservative keeps the deck's
    #: identity; free will use any legal owned card. Different products, labelled.
    conservative: Repair | None = None
    free: Repair | None = None
    #: The best deck they can definitely build from what we already know.
    floor: Deck | None = None
    feasibility: Feasibility | None = None
    question: Question | None = None
    reason: str = ""

    @property
    def has_answer(self) -> bool:
        return self.floor is not None



@dataclass(frozen=True)
class Engine:
    """Everything a session needs that does not change between rounds."""
    catalog: Catalog
    rules: BoundRules
    profile: LegendProfile
    decks: Mapping[str, MetaDeck]
    scores: Mapping[str, float]

    # -- lifecycle ------------------------------------------------------------

    def start(self, legend_id: str, *, prior: Knowledge | None = None) -> Session:
        return Session(legend_id=legend_id, knowledge=prior or Knowledge())

    def answer(self, session: Session, deck_id: str, have: Mapping[str, int]) -> Session:
        """Record one round of answers."""
        deck = self.decks.get(deck_id)
        if deck is None:
            return session
        knowledge = session.knowledge.with_answer(deck_requirements(deck.deck), have)
        asked = session.asked if deck_id in session.asked else (*session.asked, deck_id)
        return replace(session, knowledge=knowledge, asked=asked)

    def answer_question(
        self, session: Session, have: Mapping[str, int], asked: Iterable[str]
    ) -> Session:
        """Record a checklist answer. Everything asked becomes exact, zeros included."""
        exact = dict(session.knowledge.exact)
        at_least = dict(session.knowledge.at_least)
        for card_id in asked:
            exact[card_id] = max(0, int(have.get(card_id, 0)))
            at_least.pop(card_id, None)
        return replace(
            session,
            knowledge=Knowledge(exact=exact, at_least=at_least),
            phase=PHASE_CHECKLIST,
            checklists=session.checklists + 1,
        )

    # -- the two tracks -------------------------------------------------------

    def floor(self, session: Session) -> Deck | None:
        """The best deck they can definitely build right now.

        Coherence comes from the pairing signal, which scores every candidate against
        what is already in the deck rather than against the format in general -- so the
        result is a plan rather than forty individually popular cards. It used to also
        steer toward a chosen archetype; that was measured to make decks *less* like the
        ones people actually play, and the note above ``CORE_SHARE`` in ``legend_index``
        records the numbers.
        """
        owned = session.knowledge.owned()
        return build(
            session.legend_id, owned,
            catalog=self.catalog, rules=self.rules,
            preference=self.profile.preference(),
        )

    def feasibility(self, session: Session) -> Feasibility:
        return assess(
            session.legend_id, session.knowledge.owned(),
            catalog=self.catalog, rules=self.rules,
        )

    def propose(self, session: Session) -> Proposal:
        """Decide what to ask next, and report what we can already promise."""
        floor = self.floor(session)
        feasibility = self.feasibility(session)

        candidates = self._candidates(session)
        # The first question is always a deck: the opening impression should be "here is
        # the best deck for this legend", not a checklist.
        #
        # After that the two tracks separate. While there is no floor, a direct question
        # aimed at the binding requirement reaches one far faster than another deck can —
        # measured, it is the difference between an answer at round 2 and at round 5.
        # Once a floor exists the pressure is off, and further decks are the pleasant way
        # to try to beat it.
        first_round = session.rounds == 0
        improving = floor is not None and session.rounds < MAX_PROPOSALS
        if candidates and (first_round or improving):
            deck = self._playable(self._pick(session, candidates))
            conservative = repair(
                deck.deck, session.knowledge, profile=self.profile,
                catalog=self.catalog, rules=self.rules, conservative=True,
            )
            free = None
            if conservative is None or conservative.drift > 0:
                free = repair(
                    deck.deck, session.knowledge, profile=self.profile,
                    catalog=self.catalog, rules=self.rules, conservative=False,
                )
            return Proposal(
                phase=PHASE_PROPOSE, deck=deck, conservative=conservative, free=free,
                floor=floor, feasibility=feasibility,
                reason=self._reason(session, deck, has_floor=floor is not None),
            )

        if floor is not None:
            return Proposal(
                phase=PHASE_DONE, floor=floor, feasibility=feasibility,
                reason="This is the best deck your collection supports for this legend.",
            )

        question = self._closing_question(session, feasibility)
        if question is None or not question.card_ids:
            return Proposal(
                phase=PHASE_DONE, floor=None, feasibility=feasibility,
                reason=feasibility.describe(),
            )
        return Proposal(
            phase=PHASE_CHECKLIST, floor=None, feasibility=feasibility,
            question=question, reason=question.reason,
        )

    # -- choosing the next question ------------------------------------------

    def _candidates(self, session: Session) -> list[MetaDeck]:
        """Decks still worth asking about."""
        out = []
        for deck_id, deck in self.decks.items():
            if deck_id in session.asked:
                continue
            if deck.deck.legend_id != session.legend_id:
                continue
            if sum(g.short for g in gaps_for(deck.deck, session.knowledge)) > REPAIRABLE_COPIES:
                continue  # too far out of reach to be worth a question
            out.append(deck)
        return out

    def _playable(self, meta: MetaDeck) -> MetaDeck:
        """The proposed deck with anything banned taken out.

        A banned deck still carries signal -- it was played, it won games, and its other
        cards say something true about the format -- so it stays in the meta data and
        keeps counting toward trends. What it must not do is reach the player as a
        suggestion: asking "do you own Obelisk of Power?" invites them to go and find a
        card they are not allowed to play.

        Removing it here rather than filtering the display means everything downstream
        agrees: the deck is short, the repair fills the hole from cards they can legally
        use, and the ban notice explains where the slot went.
        """
        banned = {c for c in meta.deck.all_card_ids() if self.rules.is_banned(c)}
        if not banned:
            return meta
        deck = meta.deck
        return replace(
            meta,
            deck=replace(
                deck,
                main={c: n for c, n in deck.main.items() if c not in banned},
                runes={c: n for c, n in deck.runes.items() if c not in banned},
                battlefields=tuple(c for c in deck.battlefields if c not in banned),
                sideboard={c: n for c, n in deck.sideboard.items() if c not in banned},
            ),
        )

    def _coherence(self, deck: MetaDeck, owned: Mapping[str, int]) -> float:
        """Can this deck's own archetype be fielded by this collection?"""
        cluster = self.profile.cluster_of(deck.deck_id)
        if cluster is None or not cluster.core:
            return 0.0
        return self.profile.coverage(cluster, owned)

    def _pick(self, session: Session, candidates: Sequence[MetaDeck]) -> MetaDeck:
        """The next deck to show.

        Round one is the straight best deck: the first thing a player sees should be
        "the best deck for this legend", not a strange probe. After that novelty starts
        to matter more than rank, because near-identical decks teach nothing.
        """
        if not session.asked:
            return max(candidates, key=lambda d: (self.scores.get(d.deck_id, 0.0), d.deck_id))

        owned = session.knowledge.owned()
        # How many candidates each still-unknown card would settle.
        resolves: dict[str, int] = {}
        for deck in candidates:
            for card_id in deck_requirements(deck.deck):
                if not session.knowledge.is_known(card_id):
                    resolves[card_id] = resolves.get(card_id, 0) + 1
        most = max(resolves.values(), default=1)

        def priority(deck: MetaDeck) -> tuple[float, str]:
            unknown = unknown_cards(deck.deck, session.knowledge)
            information = (
                sum(resolves.get(c, 0) for c in unknown) / (most * len(unknown))
                if unknown else 0.0
            )
            total = (
                W_QUALITY * self.scores.get(deck.deck_id, 0.0)
                + W_PLAUSIBILITY * self._plausibility(deck, session.knowledge)
                + W_INFORMATION * information
                + W_COHERENCE * self._coherence(deck, owned)
            )
            return (total, deck.deck_id)

        return max(candidates, key=priority)

    def _plausibility(self, deck: MetaDeck, knowledge: Knowledge) -> float:
        """Roughly, can they field this? Known copies, plus a rarity prior for the rest."""
        required = deck_requirements(deck.deck)
        total = sum(required.values()) or 1
        score = 0.0
        for card_id, needed in required.items():
            if knowledge.is_known(card_id):
                score += min(needed, knowledge.lower_bound(card_id))
            else:
                card = self.catalog.get(card_id)
                prior = RARITY_PRIOR.get(card.rarity, DEFAULT_PRIOR) if card else DEFAULT_PRIOR
                score += needed * prior
        return score / total

    def _reason(self, session: Session, deck: MetaDeck, *, has_floor: bool = False) -> str:
        """Why this deck is on screen, said to the player rather than about ourselves.

        "Asks about 4 cards we have not covered yet" describes our information problem;
        the player's question is whether this round is worth their time. Once a deck is
        already secured that answer is "only if you want a better one", and saying so is
        what makes the round feel optional instead of endless.
        """
        if not session.asked:
            return "The strongest recent deck for this legend."
        if has_floor:
            # No card count here. A deck round assumes you own what it does not ask
            # about, so those cards look identical on screen -- quoting a number the
            # player cannot point at makes the whole page feel less trustworthy, not
            # more informed.
            return (
                "You already have a deck you can build. This one could be better — "
                "mark anything you are missing, or stop here and keep what you have."
            )
        return "Closer to what you own. Mark anything you are missing."

    # -- the closing question -------------------------------------------------

    def _closing_question(
        self, session: Session, feasibility: Feasibility
    ) -> Question | None:
        """Ask about everything that is still blocking, in one question.

        Driven by *which* requirements are short rather than by a generic checklist —
        that is what keeps it to one screen instead of the legend's whole legal pool.

        Every blocking requirement goes into the same question. Asking them one at a
        time looked tidier and cost a round each: a session short of both a champion and
        six cards spent one round on a two-card question and another on a twelve-card
        one, when a single screen would have closed both.
        """
        blocking = feasibility.blocking
        legend = self.catalog.get(session.legend_id)
        if not blocking or legend is None:
            return None
        knowledge = session.knowledge
        copy_limit = self.rules.int_constraint("main_copy_limit", 3)

        def ranked(cards: Iterable[str]) -> list[str]:
            """Unasked cards first, then ones we only have a lower bound for.

            A card seen in a deck is not a card we know the count of — "I have all 6"
            leaves open that they hold twelve. When the unknowns run out, those are
            exactly the cards worth pinning down, so they follow rather than being
            excluded.
            """
            unknown, partial = [], []
            for card_id in cards:
                if knowledge.is_exact(card_id):
                    continue
                (partial if knowledge.is_known(card_id) else unknown).append(card_id)
            by_play = lambda c: (-self.profile.play_rate.get(c, 0.0), c)  # noqa: E731
            return sorted(unknown, key=by_play) + sorted(partial, key=by_play)

        def zone_pool(card_type: str) -> list[str]:
            return [
                c.card_id
                for c in legal_zone_pool(
                    legend, card_type, catalog=self.catalog, rules=self.rules
                )
            ]

        def calibration() -> float:
            """How optimistic the rarity priors have proved *for this player*.

            The priors describe an average collection, and the players who most need
            this question are the ones furthest from average. Left uncorrected the
            estimate never learns: a player who owns little of a wide pool gets the same
            dozen names every round, answers "none", and the question repeats until the
            session runs out of patience — which is exactly how a buildable collection
            got told "you cannot build this".

            So compare copies actually reported against copies the priors expected over
            everything asked so far, and scale by the ratio. Shrunk toward 1.0 while the
            sample is small so a couple of unlucky answers do not blow the question up.
            """
            answered = [c for c in knowledge.exact if self.catalog.get(c) is not None]
            if len(answered) < CALIBRATION_MIN:
                return 1.0
            got = sum(min(copy_limit, knowledge.exact[c]) for c in answered)
            expected = sum(
                copy_limit * RARITY_PRIOR.get(
                    self.catalog.get(c).rarity, DEFAULT_PRIOR  # type: ignore[union-attr]
                )
                for c in answered
            )
            if expected <= 0:
                return 1.0
            weight = len(answered) / (len(answered) + CALIBRATION_MIN)
            ratio = (got / expected) * weight + (1.0 - weight)
            return max(CALIBRATION_FLOOR, min(1.0, ratio))

        def enough_to_close(cards: list[str], short_by: int) -> list[str]:
            """Enough names that the expected copies clear the shortfall with margin.

            Sizing by a fixed count assumes earlier deck rounds already covered ground.
            For a legend with two published decks there were no such rounds, so this
            question carries the whole load; walking until the expected yield clears the
            gap self-tunes — a list of commons closes it quickly, epics need more names.

            Once a previous question has already come back short, stop estimating and
            ask the rest of the pool. Saying "you cannot build this" while holding names
            we never asked about is a guess, and it is the one failure the acceptance
            criterion does not allow; a longer checklist is a far smaller cost to the
            player than a wrong no.
            """
            if session.checklists >= SWEEP_AFTER:
                return cards
            chosen: list[str] = []
            expected = 0.0
            target = short_by * CHECKLIST_MARGIN
            rate = calibration()
            for card_id in cards:
                if expected >= target and len(chosen) >= MIN_CHECKLIST:
                    break
                if len(chosen) >= MAX_CHECKLIST:
                    break
                card = self.catalog.get(card_id)
                prior = RARITY_PRIOR.get(card.rarity, DEFAULT_PRIOR) if card else DEFAULT_PRIOR
                expected += copy_limit * prior * rate
                chosen.append(card_id)
            return chosen

        asks: list[str] = []
        wants: list[str] = []
        for requirement in blocking:
            if requirement.name == REQ_LEGEND:
                asks.append(session.legend_id)
                wants.append(legend.name)
            elif requirement.name == REQ_CHAMPION:
                pool = ranked(
                    c.card_id
                    for c in legal_champions(legend, catalog=self.catalog, rules=self.rules)
                )
                asks.extend(pool[:12])
                wants.append("a champion")
            elif requirement.name == REQ_RUNES:
                # Only a couple of rune types are ever legal for a legend, so every one
                # of them fits in the same question.
                asks.extend(ranked(zone_pool("Rune")))
                wants.append(_plural(requirement.short_by, "more rune"))
            elif requirement.name == REQ_BATTLEFIELDS:
                asks.extend(ranked(zone_pool("Battlefield"))[:12])
                wants.append(_plural(requirement.short_by, "more battlefield"))
            elif requirement.name == REQ_MAIN:
                pool = ranked(
                    c.card_id
                    for c in legal_main_pool(legend, catalog=self.catalog, rules=self.rules)
                )
                asks.extend(enough_to_close(pool, requirement.short_by))
                wants.append(_plural(requirement.short_by, "more card"))

        card_ids = tuple(dict.fromkeys(a for a in asks if not knowledge.is_exact(a)))
        if not card_ids:
            return None
        need = wants[0] if len(wants) == 1 else ", ".join(wants[:-1]) + f" and {wants[-1]}"
        return Question(f"You still need {need}. Which of these do you own?", card_ids)



@dataclass(frozen=True)
class Run:
    """A completed session, and how long each thing took.

    ``rounds_to_answer`` is the number that matters to a player: how many questions
    before we could show them something they can actually build. It is not the same as
    ``rounds``, because the session keeps proposing after it has an answer in order to
    beat it — the floor is on screen throughout, so they can stop whenever they like.
    """
    session: Session
    proposal: Proposal
    rounds: int
    rounds_to_answer: int | None
    floor: Deck | None



def run_to_completion(
    engine: Engine,
    legend_id: str,
    truth: Mapping[str, int],
    *,
    max_rounds: int = 12,
    stop_at_answer: bool = False,
) -> Run:
    """Drive a whole session, answering truthfully from a known collection.

    The clearest statement of the loop: propose, answer, repeat until there is an answer
    and nothing better left to ask.
    """
    session = engine.start(legend_id)
    proposal = engine.propose(session)
    rounds = 0
    rounds_to_answer = 0 if proposal.floor is not None else None
    floor = proposal.floor

    while rounds < max_rounds:
        if proposal.phase == PHASE_DONE:
            break
        if stop_at_answer and floor is not None:
            break
        rounds += 1
        if proposal.phase == PHASE_PROPOSE and proposal.deck is not None:
            required = deck_requirements(proposal.deck.deck)
            have = {c: min(n, int(truth.get(c, 0))) for c, n in required.items()}
            session = engine.answer(session, proposal.deck.deck_id, have)
        elif proposal.question is not None:
            asked = proposal.question.card_ids
            have = {c: int(truth.get(c, 0)) for c in asked}
            session = engine.answer_question(session, have, asked)
        else:
            break
        proposal = engine.propose(session)
        if proposal.floor is not None:
            floor = proposal.floor
            if rounds_to_answer is None:
                rounds_to_answer = rounds

    return Run(
        session=session, proposal=proposal, rounds=rounds,
        rounds_to_answer=rounds_to_answer, floor=floor,
    )
