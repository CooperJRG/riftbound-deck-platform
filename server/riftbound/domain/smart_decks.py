"""Smart Decks: the guided builder.

Pick a legend, get shown the best deck for it, say what you're short, repeat. The
session engine here is pure — it takes a knowledge state and returns the next question —
so the whole loop can be simulated and measured without a browser or a database.

Two ideas do the work.

**Two tracks, every round.** The *floor* is the best deck the player can definitely build
from what we already know; it is recomputed after every answer and can only improve. The
*ceiling* keeps proposing high-evidence decks to beat it. Selection alone could never
guarantee an answer — a published deck is an exact 40-card list, and if none fits, the
player is told "no" while owning plenty to build something legal. Construction is the
guarantee; selection is the upgrade.

**Questions are chosen for what they resolve.** Decks for one legend overlap at a median
Jaccard of 0.57, so proposing decks in score order asks about the same cards over and
over. Weighting a candidate by how many *other* candidates its unknown cards would settle
is the difference between four rounds and fifteen.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Iterable, Mapping, Sequence

from .cards import Catalog
from .deck import Deck
from .deck_builder import (
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
from .legend_index import LegendProfile, substitutes
from .meta import MetaDeck
from .rules import BoundRules
from .validator import validate

PHASE_PROPOSE = "propose"
PHASE_CHECKLIST = "checklist"
PHASE_DONE = "done"

#: How many decks to show before falling back to a direct checklist. Coverage measured
#: on the snapshot: 3-4 decks cover half a legend's card pool, and the curve flattens
#: after that, so a fifth proposal buys much less than simply asking.
MAX_PROPOSALS = 4

#: A deck this many copies short is repaired rather than discarded.
REPAIRABLE_COPIES = 12

#: Weights for choosing the next deck to ask about.
W_QUALITY = 0.45
W_PLAUSIBILITY = 0.25
W_INFORMATION = 0.30

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


@dataclass(frozen=True)
class Knowledge:
    """What we know about a player's collection, and how firmly.

    ``exact`` is what they told us. ``at_least`` is inferred: a card that appeared in a
    deck we showed and was *not* marked means they have at least what that deck asked
    for. That inference is why a few rounds settle so much — an unmarked three-of pins
    the card at the copy limit, which answers it for every future deck.
    """
    exact: Mapping[str, int] = field(default_factory=dict)
    at_least: Mapping[str, int] = field(default_factory=dict)

    def lower_bound(self, card_id: str) -> int:
        """The most copies we can safely assume. Never over-claims."""
        return max(int(self.exact.get(card_id, 0)), int(self.at_least.get(card_id, 0)))

    def is_exact(self, card_id: str) -> bool:
        return card_id in self.exact

    def is_known(self, card_id: str) -> bool:
        return card_id in self.exact or card_id in self.at_least

    def owned(self) -> dict[str, int]:
        """A collection the constructor may build from — lower bounds only."""
        cards = set(self.exact) | set(self.at_least)
        return {c: self.lower_bound(c) for c in cards if self.lower_bound(c) > 0}

    def with_answer(
        self, required: Mapping[str, int], have: Mapping[str, int]
    ) -> "Knowledge":
        """Fold one round's answers in.

        A deck answer only ever reveals ownership *up to what that deck asked for*. The
        screen says "Need 6 — you have [0..6]", so "I have all 6" means **at least** six,
        not exactly six. Recording it as exact silently caps the collection at whatever
        the first deck happened to want: a player with twelve Calm Runes was written down
        as having six, then told they were one rune short of a deck they could build.

        Only a shortfall is exact, because a player saying "I have 2 of the 3" has told
        us the true number.
        """
        exact = dict(self.exact)
        at_least = dict(self.at_least)
        for card_id, needed in required.items():
            reported = int(have[card_id]) if card_id in have else int(needed)
            if reported < int(needed):
                exact[card_id] = max(0, reported)
                at_least.pop(card_id, None)
            elif card_id not in exact:
                at_least[card_id] = max(int(at_least.get(card_id, 0)), int(needed))
        return Knowledge(exact=exact, at_least=at_least)

    @classmethod
    def from_collection(cls, owned: Mapping[str, int]) -> "Knowledge":
        """Seed from a recorded collection, which is exact by definition."""
        return cls(exact={k: int(v) for k, v in owned.items() if int(v) > 0})


def _plural(count: int, noun: str) -> str:
    """"1 more card", not "1 more cards".

    Trivial, and worth doing: this string is the wizard talking to a player at the exact
    moment it is asking them for effort, and sloppy copy there reads as a sloppy answer.
    """
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def deck_requirements(deck: Deck) -> dict[str, int]:
    """Every card a deck needs, with copies, across all zones."""
    required = dict(deck.main)
    for card_id, qty in deck.runes.items():
        required[card_id] = required.get(card_id, 0) + qty
    for card_id in deck.battlefields:
        required[card_id] = required.get(card_id, 0) + 1
    if deck.legend_id:
        required[deck.legend_id] = max(required.get(deck.legend_id, 0), 1)
    return required


# -- gaps and repair ----------------------------------------------------------


@dataclass(frozen=True)
class Gap:
    """A shortfall on one card, measured in copies."""
    card_id: str
    needed: int
    have: int

    @property
    def short(self) -> int:
        return max(0, self.needed - self.have)


@dataclass(frozen=True)
class Swap:
    out_card_id: str
    in_card_id: str
    copies: int
    reason: str


@dataclass(frozen=True)
class Repair:
    """A deck adjusted to what the player owns, and how far it moved."""
    deck: Deck
    swaps: tuple[Swap, ...]
    kind: str            # "conservative" | "free"
    drift: int           # copies changed

    @property
    def changed(self) -> bool:
        return self.drift > 0


def gaps_for(deck: Deck, knowledge: Knowledge) -> tuple[Gap, ...]:
    """What the player is short for this deck. Only counts what we actually know."""
    out = []
    for card_id, needed in deck_requirements(deck).items():
        if not knowledge.is_known(card_id):
            continue
        have = knowledge.lower_bound(card_id)
        if have < needed:
            out.append(Gap(card_id, needed, have))
    return tuple(sorted(out, key=lambda g: (-g.short, g.card_id)))


def unknown_cards(deck: Deck, knowledge: Knowledge) -> tuple[str, ...]:
    return tuple(
        sorted(c for c in deck_requirements(deck) if not knowledge.is_known(c))
    )


@dataclass
class _Zones:
    """A deck's mutable zones during a repair, with the rules each one obeys.

    The sideboard is carried but never modified: the copy limit is a *combined*
    main-plus-sideboard rule, so a repair that only counts main-deck copies will happily
    add a fourth copy of a card already sitting in the sideboard.
    """
    main: dict[str, int]
    runes: dict[str, int]
    battlefields: list[str]
    sideboard: dict[str, int] = field(default_factory=dict)

    def container(self, zone: str):
        return {"main": self.main, "runes": self.runes}.get(zone)

    def count(self, zone: str, card_id: str) -> int:
        if zone == "battlefields":
            return self.battlefields.count(card_id)
        return self.container(zone).get(card_id, 0)

    def committed(self, zone: str, card_id: str) -> int:
        """Copies that count against this card's limit, across every zone that shares it."""
        if zone == "main":
            return self.main.get(card_id, 0) + self.sideboard.get(card_id, 0)
        return self.count(zone, card_id)

    def add(self, zone: str, card_id: str, copies: int) -> None:
        if zone == "battlefields":
            self.battlefields.extend([card_id] * copies)
            return
        bucket = self.container(zone)
        bucket[card_id] = bucket.get(card_id, 0) + copies

    def set_to(self, zone: str, card_id: str, copies: int) -> None:
        if zone == "battlefields":
            self.battlefields = [b for b in self.battlefields if b != card_id]
            self.battlefields.extend([card_id] * copies)
            return
        bucket = self.container(zone)
        if copies > 0:
            bucket[card_id] = copies
        else:
            bucket.pop(card_id, None)

    def all_cards(self) -> list[str]:
        return list(self.main) + list(self.runes) + list(self.battlefields)


def _zone_of(card) -> str:
    if card.card_type == "Rune":
        return "runes"
    if card.card_type == "Battlefield":
        return "battlefields"
    return "main"


def _zone_pool(zone: str, legend, *, catalog: Catalog, rules: BoundRules) -> set[str]:
    """Cards legal in a zone for this legend."""
    from .deck_builder import legal_main_pool

    if zone == "runes":
        return {c.card_id for c in legal_zone_pool(legend, "Rune", catalog=catalog, rules=rules)}
    if zone == "battlefields":
        return {
            c.card_id
            for c in legal_zone_pool(legend, "Battlefield", catalog=catalog, rules=rules)
        }
    return {c.card_id for c in legal_main_pool(legend, catalog=catalog, rules=rules)}


def _zone_cap(card, zone: str, *, rules: BoundRules) -> int:
    """How many copies of a card a zone may hold."""
    if zone == "battlefields":
        return 1 if rules.bool_constraint("battlefield_unique_required", False) else 3
    if zone == "runes":
        return rules.int_constraint("rune_count_exact", 12)
    if card.unique:
        return 1
    # The tighter of the two, because both are real: a format may allow three in the
    # main deck but only three across main and sideboard together.
    return min(
        rules.int_constraint("main_copy_limit", 3),
        rules.int_constraint(
            "combined_main_sideboard_copy_limit",
            rules.int_constraint("main_copy_limit", 3),
        ),
    )


def repair(
    deck: Deck,
    knowledge: Knowledge,
    *,
    profile: LegendProfile,
    catalog: Catalog,
    rules: BoundRules,
    conservative: bool,
) -> Repair | None:
    """Fill a deck's holes from cards the player owns.

    A **conservative** repair draws only from the deck's own family — cards the field
    plays alongside this core — so the result is still recognisably the deck that won. A
    **free** repair will use any legal owned card: it answers far more often, but what
    comes out may share little with what was proposed. They are different products and
    the caller must label them as such.

    Returns ``None`` when the holes cannot be filled, so a caller can fall back rather
    than present a deck that is quietly illegal.
    """
    holes = gaps_for(deck, knowledge)
    if not holes:
        return Repair(deck=deck, swaps=(), kind="none", drift=0)
    if sum(g.short for g in holes) > REPAIRABLE_COPIES:
        return None

    legend = catalog.get(deck.legend_id)
    if legend is None:
        return None

    owned = knowledge.owned()
    allowed: set[str] | None = None
    if conservative:
        family = _best_cluster_for(profile, deck)
        if family is None:
            return None
        allowed = set(family.core) | set(family.flex)

    zones = _Zones(
        main=dict(deck.main), runes=dict(deck.runes), battlefields=list(deck.battlefields),
        sideboard=dict(deck.sideboard),
    )
    swaps: list[Swap] = []
    drift = 0

    for hole in holes:
        card = catalog.get(hole.card_id)
        if card is None or hole.card_id == deck.legend_id:
            return None  # a legend has no substitute
        zone = _zone_of(card)

        # Keep the copies they do own; only the shortfall needs covering.
        zones.set_to(zone, hole.card_id, hole.have)

        pool = _zone_pool(zone, legend, catalog=catalog, rules=rules)
        ranked = substitutes(
            hole.card_id, profile=profile, owned=owned, catalog=catalog,
            context=zones.all_cards(),
        )

        filled = 0
        for candidate_id, score in ranked:
            if filled >= hole.short:
                break
            if candidate_id not in pool:
                continue
            if allowed is not None and candidate_id not in allowed:
                continue
            candidate = catalog.get(candidate_id)
            if candidate is None:
                continue
            # Against the limit: every zone that shares it. Against what they own: the
            # same, since a card in the sideboard is a copy already spoken for.
            already = zones.committed(zone, candidate_id)
            room = min(
                hole.short - filled,
                owned.get(candidate_id, 0) - already,
                _zone_cap(candidate, zone, rules=rules) - already,
            )
            if room <= 0:
                continue
            zones.add(zone, candidate_id, room)
            filled += room
            swaps.append(
                Swap(
                    out_card_id=hole.card_id, in_card_id=candidate_id, copies=room,
                    reason=f"the field plays this alongside the deck {score:.0%} of the time",
                )
            )
        if filled < hole.short:
            return None
        drift += hole.short

    repaired = Deck.make(
        name=deck.name, format=deck.format, legend_id=deck.legend_id,
        champion_id=deck.champion_id, main=zones.main, runes=zones.runes,
        battlefields=zones.battlefields, sideboard=dict(deck.sideboard),
    )
    # The champion must stay in the main deck; if a swap displaced it the deck is not
    # this deck any more.
    if deck.champion_id and deck.champion_id not in repaired.main:
        return None
    # The last word, and the reason this function may return None at all. Filling holes
    # by count is not the same as producing a legal deck: a constraint this code does
    # not model -- today the combined main-and-sideboard copy limit, tomorrow something
    # else -- otherwise reaches the player as a deck labelled "not legal" that they are
    # nonetheless invited to save. Rules live in the validator; ask it.
    if not validate(repaired, rules=rules, catalog=catalog).legal:
        return None
    return Repair(
        deck=repaired, swaps=tuple(swaps),
        kind="conservative" if conservative else "free", drift=drift,
    )


def _best_cluster_for(profile: LegendProfile, deck: Deck):
    """The family whose core this deck matches most closely."""
    main = set(deck.main)
    best, best_overlap = None, 0.0
    for cluster in profile.clusters:
        if not cluster.core:
            continue
        overlap = len(cluster.core & main) / len(cluster.core)
        if overlap > best_overlap:
            best, best_overlap = cluster, overlap
    return best


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
        asked = session.asked if deck_id in session.asked else session.asked + (deck_id,)
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
        """The best deck they can definitely build right now."""
        return build(
            session.legend_id, session.knowledge.owned(),
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
            deck = self._pick(session, candidates)
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

    def _pick(self, session: Session, candidates: Sequence[MetaDeck]) -> MetaDeck:
        """The next deck to show.

        Round one is the straight best deck: the first thing a player sees should be
        "the best deck for this legend", not a strange probe. After that novelty starts
        to matter more than rank, because near-identical decks teach nothing.
        """
        if not session.asked:
            return max(candidates, key=lambda d: (self.scores.get(d.deck_id, 0.0), d.deck_id))

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
