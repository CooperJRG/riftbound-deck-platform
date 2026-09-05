"""What we know about a collection, and how sure we are of it.

The subtle part of the whole feature, and where its worst bug lived. "I have all six of
them" is a *lower bound*, not a count: recording it as exact capped a player's twelve
runes at six and then told them they were one short of a deck they could build. Only a
shortfall is ever exact.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from ..availability import AvailabilityProfile
from ..cards import Catalog
from ..deck import Deck

# -- knowledge ----------------------------------------------------------------






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
    #: Ids in ``exact`` that came from a declaration rather than an answer in session.
    #:
    #: They are exact -- the player said so -- but they are not a *sample* of the
    #: collection, and one estimate downstream depends on that difference. Calibration
    #: asks "how optimistic have the rarity priors proved for this player" by comparing
    #: copies reported against copies expected over everything asked. A declaration is
    #: chosen precisely because it is absent, so folding "no Epics" into that comparison
    #: reads as evidence the player owns little of *everything*: measured, seeding 151
    #: declared-absent cards floored the estimate and pushed the median session from 47
    #: cards to 85. Marking them keeps them exact for every purpose except the one they
    #: would bias.
    assumed: frozenset[str] = frozenset()
    #: Cards the player owns, or might, and does not want to play.
    #:
    #: A different kind of claim from anything above it. `exact` and `at_least` are facts
    #: about a collection; this is a fact about a person, and the two must not be
    #: conflated. Recording a decline as `exact 0` would make the wizard tell someone
    #: they cannot build a deck they own every card for, and would write "does not own"
    #: into their collection on the opt-in save.
    #:
    #: The whole point of the feature: the field's best deck is not everybody's best
    #: deck, and a tool that can only hear "I don't have that" can only ever build the
    #: meta back at you.
    declined: frozenset[str] = frozenset()

    def lower_bound(self, card_id: str) -> int:
        """The most copies we can safely assume. Never over-claims."""
        if card_id in self.declined:
            return 0
        return max(int(self.exact.get(card_id, 0)), int(self.at_least.get(card_id, 0)))

    def is_exact(self, card_id: str) -> bool:
        return card_id in self.exact

    def is_known(self, card_id: str) -> bool:
        return card_id in self.exact or card_id in self.at_least

    def owned(self) -> dict[str, int]:
        """A collection the constructor may build from — lower bounds only.

        Declined cards are absent. The constructor cannot reach for them, but the
        *reason* they are absent stays visible on the knowledge itself, so a caller can
        tell "you have not got it" from "you said no" -- which are the same shortfall and
        very different sentences.
        """
        cards = set(self.exact) | set(self.at_least)
        return {c: self.lower_bound(c) for c in cards if self.lower_bound(c) > 0}

    def is_declined(self, card_id: str) -> bool:
        return card_id in self.declined

    def declining(self, card_ids: Iterable[str]) -> Knowledge:
        """Rule cards out by preference. Additive, so passes accumulate."""
        wanted = {str(c) for c in card_ids if str(c)}
        if not wanted:
            return self
        return Knowledge(
            exact=dict(self.exact),
            at_least=dict(self.at_least),
            declined=self.declined | wanted,
            assumed=self.assumed,
        )

    def allowing(self, card_ids: Iterable[str]) -> Knowledge:
        """Take a decline back. A playstyle is allowed to change its mind."""
        forgiven = {str(c) for c in card_ids if str(c)}
        if not forgiven & self.declined:
            return self
        return Knowledge(
            exact=dict(self.exact),
            at_least=dict(self.at_least),
            declined=self.declined - forgiven,
            assumed=self.assumed,
        )

    def with_answer(
        self, required: Mapping[str, int], have: Mapping[str, int]
    ) -> Knowledge:
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
        # Anything they have now answered for is real evidence, not an assumption.
        return Knowledge(
            exact=exact,
            at_least=at_least,
            declined=self.declined,
            assumed=self.assumed - set(required),
        )

    @classmethod
    def from_collection(cls, owned: Mapping[str, int]) -> Knowledge:
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


#: Copies of each rune to assume. A rune base runs to twelve, so this covers any legal
#: deck without pretending to a precise count nobody stated.
ASSUMED_RUNES = 12


def declared_knowledge(
    profile: AvailabilityProfile, catalog: Catalog
) -> Knowledge:
    """What the player has already told us, before the wizard asks anything.

    The availability profile is a statement about a collection, and until now the wizard
    never read it. Somebody who ticked "no Epics" -- one click, the app's own onboarding
    path for a casual player -- was still shown every Epic in the opening checklist,
    pre-filled as *owned*, and then asked about more of them. The declaration fed a
    coverage figure on screen and nothing else.

    What may be seeded is not the same in every mode, and the difference is the whole
    care of this function:

    **Exclusion mode** names cards the player says they do not have, whether card by
    card or by rule. That is a positive claim of absence, so it seeds ``exact 0``.

    **Collection mode** lists what they *do* have, and is nearly always partial -- most
    people record the decks they play, not their binder. Positive counts seed exact
    values; silence seeds nothing, because reading "not written down" as "does not own"
    is precisely the assumption that made v2 return an empty deck four times in five.

    **Strict collection mode** is the exception, and only because the player asked for
    it by name: "only what I can build now" means absence is the answer, so zeros are
    seeded too.

    Seeded knowledge is a floor, not a verdict. Anything the player answers in the
    session overrides it, so a rule that turns out to be too broad costs one correction
    rather than a wrong deck.
    """
    exact: dict[str, int] = {}
    at_least: dict[str, int] = {}
    for card in catalog:
        # Runes are not a card anybody is short of. They are the resource base, handed
        # out in bulk and reprinted in every product, and asking a player to confirm
        # they own Body Runes spends a question on the one answer that is always yes --
        # then blocks a deck on the answer if they mistick it. Assumed available, so
        # they never appear in a checklist and never open a hole for the repair to fill.
        if card.card_type == "Rune":
            at_least[card.card_id] = ASSUMED_RUNES
            continue
        resolved = profile.resolve(card)
        if resolved.reason.startswith("excluded:"):
            exact[card.card_id] = 0
        elif resolved.reason == "owned":
            exact[card.card_id] = resolved.owned_copies
        elif resolved.reason == "owned:rule":
            # "I have the commons" is not a count. A lower bound is exactly what this
            # module already means by "I have all of them", and it leaves room for the
            # player to hold more than a playset without being written down as short.
            at_least[card.card_id] = resolved.owned_copies
        elif resolved.reason == "not-owned" and (profile.strict or card.card_id in profile.owned):
            exact[card.card_id] = 0
    return Knowledge(exact=exact, at_least=at_least, assumed=frozenset(exact))
