"""What can this player realistically build with?

v2 wired "my collection" into the deck builder as a hard constraint. Its own
evaluation recorded the result: ``strictBuildableEmptyResultRate: 0.814`` -- asked for
a deck from the user's collection, it returned nothing four times in five. And it
demanded that a user document thousands of cards before they got anything at all.

This module replaces that with a single resolved function::

    profile.resolve(card) -> Availability(weight, max_copies, ...)

Two ways to populate it, one thing consumed downstream:

**Collection mode** -- "here is what I own." Precise, but expensive to set up and
stale the moment a set releases.

**Exclusion mode** -- "here is what I *don't* have." The onboarding-friendly default:
name the handful of cards you are missing (or check "no Epics") and start building
immediately. It is also self-healing across releases -- new cards are available by
default, so a new set never invalidates your setup.

Both are **soft by default**. An unavailable card is de-emphasised, never banned, so
the builder can always produce a legal deck. ``strict=True`` opts in to a hard
restriction for the "what can I build *right now*, tonight" question.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from .cards import Card, Catalog

MODE_OPEN = "open"
MODE_COLLECTION = "collection"
MODE_EXCLUSION = "exclusion"
MODES = (MODE_OPEN, MODE_COLLECTION, MODE_EXCLUSION)

#: Weight applied to a card the player probably cannot field. Low enough that the
#: builder reaches for it only when nothing comparable exists, high enough that it
#: still can -- which is the difference between "here is a deck" and v2's empty result.
DEFAULT_PENALTY = 0.15

# Exclusion rule kinds. Each is a one-click alternative to naming cards individually.
RULE_RARITY = "rarity"          # "I don't have Epics"
RULE_SET = "set"                # "I don't have anything from Unleashed"
RULE_SUPER_TYPE = "super_type"  # "I don't have Signature cards"
RULE_PROMO_ONLY = "promo_only"  # "I don't have promo/Showcase-only cards"
RULE_KINDS = (RULE_RARITY, RULE_SET, RULE_SUPER_TYPE, RULE_PROMO_ONLY)


#: Copies a rule-declared card is assumed to supply. Not a count -- the player said
#: "I have the commons", not "I have exactly three of each" -- so this is seeded as a
#: lower bound downstream, which is the semantics :mod:`smart_decks.knowledge` already
#: has for "I have all of them".
RULE_COPIES = 3
#: Runes are bought in bulk or not at all, and a rune base wants twelve.
RULE_RUNE_COPIES = 12


@dataclass(frozen=True)
class CardRule:
    """A predicate selecting a class of cards.

    The predicate is the same whichever direction it is used in -- "no Epics" and "every
    Common" differ only in what the caller does with a match -- so the matching lives
    here and the polarity lives in the subclasses.
    """
    kind: str
    value: str = ""

    def matches(self, card: Card) -> bool:
        if self.kind == RULE_RARITY:
            return card.rarity.casefold() == self.value.casefold()
        if self.kind == RULE_SET:
            return self.value.upper() in card.set_codes
        if self.kind == RULE_SUPER_TYPE:
            return card.super_type.casefold() == self.value.casefold()
        if self.kind == RULE_PROMO_ONLY:
            # Every printing is a promo/Showcase -- the card is hard to obtain.
            return bool(card.printings) and all(
                p.promo or p.rarity == "Showcase" for p in card.printings
            )
        return False

    def copies_for(self, card: Card) -> int:
        return RULE_RUNE_COPIES if card.card_type == "Rune" else RULE_COPIES


@dataclass(frozen=True)
class ExclusionRule(CardRule):
    """A class of cards the player says they do not have.

    Lets a casual player express "I only have the starter and a few packs" in one
    click instead of a data-entry session.
    """

    def describe(self) -> str:
        return {
            RULE_RARITY: f"no {self.value} cards",
            RULE_SET: f"nothing from {self.value}",
            RULE_SUPER_TYPE: f"no {self.value} cards",
            RULE_PROMO_ONLY: "no promo-only cards",
        }.get(self.kind, self.kind)


@dataclass(frozen=True)
class OwnedRule(CardRule):
    """A class of cards the player says they *do* have.

    The missing half of the entry story. Exclusion is the right polarity for somebody
    who owns nearly everything and is naming the gaps; it is the wrong one for somebody
    who owns a fraction of the pool, who would have to name thousands of cards to say
    something true. "Everything Common from OGN" is one click and covers hundreds.
    """

    def describe(self) -> str:
        return {
            RULE_RARITY: f"all {self.value}s",
            RULE_SET: f"everything from {self.value}",
            RULE_SUPER_TYPE: f"all {self.value} cards",
            RULE_PROMO_ONLY: "all promo-only cards",
        }.get(self.kind, self.kind)


@dataclass(frozen=True)
class Availability:
    """Resolved availability of one card."""
    card_id: str
    weight: float           # 0.0-1.0 preference multiplier applied by the builder
    max_copies: int | None  # hard cap; None means "rules limit only"
    owned_copies: int       # known owned copies (0 in exclusion mode)
    available: bool         # would a strict build accept this card at all?
    reason: str             # machine-readable, e.g. "excluded:rarity=Epic"

    @property
    def is_penalised(self) -> bool:
        return self.weight < 1.0


@dataclass(frozen=True)
class AvailabilityProfile:
    """How to judge whether a player can field a given card.

    ``mode`` selects how the profile is populated; everything downstream only ever
    calls :meth:`resolve`, so the builder, the scorer and the UI need no knowledge of
    which mode the player chose.
    """
    mode: str = MODE_OPEN
    owned: Mapping[str, int] = field(default_factory=dict)   # card_id -> copies
    excluded_cards: frozenset[str] = frozenset()             # card_id
    exclusion_rules: tuple[ExclusionRule, ...] = ()
    #: Classes of card the player says they own, for collection mode. Counted cards in
    #: ``owned`` always win: a rule is a broad statement, a count is a specific one.
    owned_rules: tuple[OwnedRule, ...] = ()
    penalty: float = DEFAULT_PENALTY
    strict: bool = False

    def __post_init__(self) -> None:
        if self.mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}, got {self.mode!r}")
        if not 0.0 <= self.penalty <= 1.0:
            raise ValueError(f"penalty must be between 0 and 1, got {self.penalty}")

    # -- construction -----------------------------------------------------------

    @classmethod
    def open_profile(cls) -> AvailabilityProfile:
        """No constraints -- every card fully available."""
        return cls(mode=MODE_OPEN)

    @classmethod
    def from_collection(
        cls,
        owned: Mapping[str, int],
        *,
        rules: Iterable[OwnedRule] = (),
        strict: bool = False,
        penalty: float = DEFAULT_PENALTY,
    ) -> AvailabilityProfile:
        clean = {
            str(k).strip().lower(): max(0, int(v))
            for k, v in owned.items()
            if str(k).strip()
        }
        return cls(
            mode=MODE_COLLECTION,
            owned=clean,
            owned_rules=tuple(rules),
            strict=strict,
            penalty=penalty,
        )

    @classmethod
    def from_exclusions(
        cls,
        card_ids: Iterable[str] = (),
        rules: Iterable[ExclusionRule] = (),
        *,
        strict: bool = False,
        penalty: float = DEFAULT_PENALTY,
    ) -> AvailabilityProfile:
        return cls(
            mode=MODE_EXCLUSION,
            excluded_cards=frozenset(
                str(c).strip().lower() for c in card_ids if str(c).strip()
            ),
            exclusion_rules=tuple(rules),
            strict=strict,
            penalty=penalty,
        )

    # -- the one method everything downstream uses ------------------------------

    def resolve(self, card: Card) -> Availability:
        """Resolve one card. Total -- never raises, never returns None."""
        if self.mode == MODE_OPEN:
            return Availability(card.card_id, 1.0, None, 0, True, "open")

        if self.mode == MODE_COLLECTION:
            owned = int(self.owned.get(card.card_id, 0))
            if card.card_id not in self.owned:
                for rule in self.owned_rules:
                    if rule.matches(card):
                        return Availability(
                            card_id=card.card_id,
                            weight=1.0,
                            max_copies=None,
                            owned_copies=rule.copies_for(card),
                            available=True,
                            # Distinguished from a counted card on purpose: this is
                            # "I have those", not "I have exactly three", and it is
                            # seeded downstream as a lower bound rather than a count.
                            reason="owned:rule",
                        )
            if owned > 0:
                return Availability(
                    card_id=card.card_id,
                    weight=1.0,
                    max_copies=owned if self.strict else None,
                    owned_copies=owned,
                    available=True,
                    reason="owned",
                )
            return Availability(
                card_id=card.card_id,
                weight=0.0 if self.strict else self.penalty,
                max_copies=0 if self.strict else None,
                owned_copies=0,
                available=not self.strict,
                reason="not-owned",
            )

        # MODE_EXCLUSION
        reason = ""
        if card.card_id in self.excluded_cards:
            reason = "excluded:card"
        else:
            for rule in self.exclusion_rules:
                if rule.matches(card):
                    reason = (
                        f"excluded:{rule.kind}={rule.value}"
                        if rule.value
                        else f"excluded:{rule.kind}"
                    )
                    break
        if not reason:
            return Availability(card.card_id, 1.0, None, 0, True, "available")
        return Availability(
            card_id=card.card_id,
            weight=0.0 if self.strict else self.penalty,
            max_copies=0 if self.strict else None,
            owned_copies=0,
            available=not self.strict,
            reason=reason,
        )

    # -- convenience ------------------------------------------------------------

    def resolve_all(self, catalog: Catalog) -> dict[str, Availability]:
        return {card.card_id: self.resolve(card) for card in catalog}

    def describe(self) -> str:
        """Human-readable summary for the UI."""
        if self.mode == MODE_OPEN:
            return "Using every card in the game."
        qualifier = "Excluding" if self.strict else "De-emphasising"
        if self.mode == MODE_COLLECTION:
            held: list[str] = []
            if self.owned:
                total = sum(self.owned.values())
                held.append(f"{total} copies recorded")
            held.extend(rule.describe() for rule in self.owned_rules)
            if not held:
                return "No collection recorded yet."
            return f"You have {', '.join(held)}. {qualifier} everything else."
        parts: list[str] = []
        if self.excluded_cards:
            n = len(self.excluded_cards)
            parts.append(f"{n} card{'s' if n != 1 else ''}")
        parts.extend(rule.describe() for rule in self.exclusion_rules)
        if not parts:
            return "Using every card in the game."
        return f"{qualifier}: {', '.join(parts)}."


#: Scarcest last. Used for stable ordering wherever a bill is rendered, so "3 Rares and
#: 2 Epics" always reads in the same direction.
RARITY_ORDER = ("Common", "Uncommon", "Rare", "Epic", "Showcase")


@dataclass(frozen=True)
class DeckCost:
    """What a deck asks of a collection, in the only currency the app can see.

    The app had no notion of what a deck costs. Every ``budget`` in the tree was the
    meta-refresh time budget, and the first question a player short of cards asks --
    "can I afford this?" -- had no answer anywhere in the product.

    Two rollups, because there are two questions and they come apart:

    ``short`` is *what you still need*, relative to what the player has told us. It is
    the honest answer to "what would this cost me", and it is empty for somebody who has
    told us nothing -- which is correct, not a bug: we cannot bill them for cards we have
    no reason to think they lack.

    ``composition`` is the deck's whole rarity makeup, independent of any collection. It
    is what makes a deck legible on **day zero of a new set**, when there is no meta
    evidence, no play rate and no collection -- rarity is printed on the card, so it is
    the one accessibility signal that exists before anything has been played.
    """
    short: Mapping[str, int] = field(default_factory=dict)
    composition: Mapping[str, int] = field(default_factory=dict)

    @property
    def copies_short(self) -> int:
        return sum(self.short.values())

    @property
    def scarce_short(self) -> int:
        """Copies short of the rarities that are actually hard to get."""
        return sum(n for r, n in self.short.items() if r in ("Rare", "Epic", "Showcase"))

    @property
    def is_affordable(self) -> bool:
        return self.copies_short == 0

    def describe(self) -> str:
        """The bill, scarcest first -- that is the part somebody balks at."""
        if not self.short:
            return "You can field this deck."
        parts = [
            f"{self.short[r]} {r}{'s' if self.short[r] != 1 else ''}"
            for r in reversed(RARITY_ORDER)
            if self.short.get(r)
        ]
        if not parts:
            return "You can field this deck."
        listed = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + f" and {parts[-1]}"
        return f"Needs {listed} you do not have."


@dataclass(frozen=True)
class DeckCoverage:
    """How well a finished deck matches what the player can field."""
    total_copies: int
    available_copies: int
    penalised_copies: int
    missing: tuple[tuple[str, int, str], ...]  # (card_id, copies_short, reason)
    #: The same walk, priced. Carried here rather than computed alongside so that
    #: "you are missing 4 cards" and "needs 2 Epics" cannot describe different cards.
    cost: DeckCost = field(default_factory=lambda: DeckCost())

    @property
    def ratio(self) -> float:
        return 1.0 if self.total_copies == 0 else self.available_copies / self.total_copies

    @property
    def is_complete(self) -> bool:
        return not self.missing


def deck_coverage(
    counts: Mapping[str, int], *, profile: AvailabilityProfile, catalog: Catalog
) -> DeckCoverage:
    """Report which cards in a deck the player likely cannot field.

    Drives the "you are missing 4 cards" readout. Unknown cards are reported, never
    dropped -- a card the current bundle does not know is a data problem to surface,
    not a card to silently delete from someone's deck.
    """
    total = available = penalised = 0
    missing: list[tuple[str, int, str]] = []
    short: dict[str, int] = {}
    composition: dict[str, int] = {}

    def bill(rarity: str, copies: int) -> None:
        short[rarity] = short.get(rarity, 0) + copies

    for card_id, qty in counts.items():
        copies = max(0, int(qty))
        if copies == 0:
            continue
        total += copies
        card = catalog.get(card_id)
        rarity = card.rarity if card and card.rarity else "Unknown"
        composition[rarity] = composition.get(rarity, 0) + copies
        if card is None:
            missing.append((card_id, copies, "unknown-card"))
            bill(rarity, copies)
            continue
        state = profile.resolve(card)
        if profile.mode == MODE_COLLECTION and state.owned_copies:
            have = min(copies, state.owned_copies)
            available += have
            if copies > have:
                penalised += copies - have
                missing.append((card_id, copies - have, "not-enough-copies"))
                bill(rarity, copies - have)
        elif state.is_penalised:
            penalised += copies
            missing.append((card_id, copies, state.reason))
            bill(rarity, copies)
        else:
            available += copies
    return DeckCoverage(
        total, available, penalised, tuple(missing),
        cost=DeckCost(short=short, composition=composition),
    )


def deck_cost(
    counts: Mapping[str, int], *, profile: AvailabilityProfile, catalog: Catalog
) -> DeckCost:
    """Price a deck against a collection, and describe its makeup regardless.

    A convenience for callers who want only the bill. It is the same walk that produces
    coverage, not a second one -- pricing a deck separately would be two chances to
    answer "which cards are missing" differently, with the player looking at both
    answers at once.
    """
    return deck_coverage(counts, profile=profile, catalog=catalog).cost
