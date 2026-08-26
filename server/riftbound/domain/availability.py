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


@dataclass(frozen=True)
class ExclusionRule:
    """A predicate marking a whole class of cards as not-owned.

    Lets a casual player express "I only have the starter and a few packs" in one
    click instead of a data-entry session.
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

    def describe(self) -> str:
        return {
            RULE_RARITY: f"no {self.value} cards",
            RULE_SET: f"nothing from {self.value}",
            RULE_SUPER_TYPE: f"no {self.value} cards",
            RULE_PROMO_ONLY: "no promo-only cards",
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
            owned={k: v for k, v in clean.items() if v > 0},
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
            total = sum(self.owned.values())
            return f"{qualifier} cards outside your collection ({total} copies owned)."
        parts: list[str] = []
        if self.excluded_cards:
            n = len(self.excluded_cards)
            parts.append(f"{n} card{'s' if n != 1 else ''}")
        parts.extend(rule.describe() for rule in self.exclusion_rules)
        if not parts:
            return "Using every card in the game."
        return f"{qualifier}: {', '.join(parts)}."


@dataclass(frozen=True)
class DeckCoverage:
    """How well a finished deck matches what the player can field."""
    total_copies: int
    available_copies: int
    penalised_copies: int
    missing: tuple[tuple[str, int, str], ...]  # (card_id, copies_short, reason)

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
    for card_id, qty in counts.items():
        copies = max(0, int(qty))
        if copies == 0:
            continue
        total += copies
        card = catalog.get(card_id)
        if card is None:
            missing.append((card_id, copies, "unknown-card"))
            continue
        state = profile.resolve(card)
        if profile.mode == MODE_COLLECTION and state.owned_copies:
            have = min(copies, state.owned_copies)
            available += have
            if copies > have:
                penalised += copies - have
                missing.append((card_id, copies - have, "not-enough-copies"))
        elif state.is_penalised:
            penalised += copies
            missing.append((card_id, copies, state.reason))
        else:
            available += copies
    return DeckCoverage(total, available, penalised, tuple(missing))
