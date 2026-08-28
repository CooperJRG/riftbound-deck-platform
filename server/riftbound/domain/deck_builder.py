"""Can this collection make a legal deck for this legend — and if so, which one?

Two pure functions, and they are the load-bearing part of Smart Decks.

:func:`assess` answers *whether* a legal deck is possible from a set of owned cards. It
is a counting check, not a search: the format's constraints are near-independent once
the pool is filtered to the legend's domain identity, so capacity can be summed. That
matters twice over — it is cheap enough to run after every answer the user gives, and
when it says "no" it says exactly **which** requirement is short, which is what lets the
wizard ask a good next question instead of a generic one.

:func:`build` then chooses *which* cards, given a preference signal (how much the meta
plays each card for this legend). Greedy, because the constraints do not interact much;
the one that does — the cap on signature cards — is tracked as the fill proceeds.

Deliberately not a learned model. The autopsy's finding stands: v2's mixture-of-experts
could not explain a single recommendation, and its synergy clusters scored a silhouette
of 0.026. Frequency over three thousand real decks is a stronger signal *and* can be
shown to the player.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass

from .cards import Card, Catalog
from .deck import Deck
from .rules import BoundRules

#: The parts of a deck that have to be filled, in the order a player would notice them
#: missing. Used for stable reporting.
REQ_LEGEND = "legend"
REQ_CHAMPION = "champion"
REQ_MAIN = "main"
REQ_RUNES = "runes"
REQ_BATTLEFIELDS = "battlefields"


@dataclass(frozen=True)
class Requirement:
    """One thing a legal deck needs, and whether the pool can supply it."""
    name: str
    needed: int
    available: int
    detail: str = ""

    @property
    def satisfied(self) -> bool:
        return self.available >= self.needed

    @property
    def short_by(self) -> int:
        return max(0, self.needed - self.available)


@dataclass(frozen=True)
class Feasibility:
    """Whether a legal deck is possible, and what is stopping it if not."""
    legend_id: str
    requirements: tuple[Requirement, ...]

    @property
    def ok(self) -> bool:
        return all(r.satisfied for r in self.requirements)

    @property
    def blocking(self) -> tuple[Requirement, ...]:
        """The requirements that are short. Empty when feasible."""
        return tuple(r for r in self.requirements if not r.satisfied)

    def requirement(self, name: str) -> Requirement | None:
        return next((r for r in self.requirements if r.name == name), None)

    def describe(self) -> str:
        if self.ok:
            return "You can build a legal deck with this legend."
        parts = [f"{r.short_by} more {r.name}" for r in self.blocking]
        return "Short by " + ", ".join(parts) + "."


def _owned(owned: Mapping[str, int], card_id: str) -> int:
    return max(0, int(owned.get(card_id, 0)))


def copy_cap(card: Card, *, rules: BoundRules) -> int:
    """How many copies of a card a main deck may legally contain.

    A card whose own text lifts the limit is bounded only by the deck size -- there is
    no legal ceiling below that, and imposing one would make a whole archetype
    unbuildable.
    """
    if card.unique:
        return 1
    if card.unlimited_copies:
        return max(0, rules.int_constraint("main_deck_size_exact", 0)) or 99
    return max(0, rules.int_constraint("main_copy_limit", 3))


def legal_main_pool(legend: Card, *, catalog: Catalog, rules: BoundRules) -> list[Card]:
    """Cards this legend may play in the main deck, regardless of ownership."""
    allowed = set(rules.list_constraint("allowed_main_card_types"))
    enforce = rules.bool_constraint("domain_identity_enforced", True)
    domains = set(legend.domains) if (enforce and legend.domains_ok) else set()
    return [
        card
        for card in catalog
        if card.card_type in allowed
        and not rules.is_banned(card.card_id)
        and card.in_domains(domains)
    ]


def legal_zone_pool(
    legend: Card, card_type: str, *, catalog: Catalog, rules: BoundRules
) -> list[Card]:
    """Runes or battlefields this legend may play."""
    enforce = rules.bool_constraint("domain_identity_enforced", True)
    domains = set(legend.domains) if (enforce and legend.domains_ok) else set()
    return [
        card
        for card in catalog
        if card.card_type == card_type
        and not rules.is_banned(card.card_id)
        and card.in_domains(domains)
    ]


def legal_champions(legend: Card, *, catalog: Catalog, rules: BoundRules) -> list[Card]:
    """Champions that may be nominated for this legend.

    A champion must share a champion tag with the legend and sit in the main deck, so
    the pool is the intersection of "legal in main" and "tags overlap".
    """
    champion_super = rules.str_constraint("champion_super_type", "Champion")
    legend_tags = {t.casefold() for t in legend.champion_tags}
    out = []
    for card in legal_main_pool(legend, catalog=catalog, rules=rules):
        if card.super_type != champion_super:
            continue
        if legend_tags and not ({t.casefold() for t in card.champion_tags} & legend_tags):
            continue
        out.append(card)
    return out


def _main_capacity(
    pool: Iterable[Card], owned: Mapping[str, int], *, rules: BoundRules
) -> int:
    """How many main-deck copies this pool can actually supply.

    Signature cards are capped as a group, so they are counted separately: a collection
    made mostly of signatures cannot fill 40 slots even if the raw copy count says so.
    """
    signature_limit = rules.int_constraint("signature_max_total", 0)
    ordinary = 0
    signature = 0
    for card in pool:
        usable = min(_owned(owned, card.card_id), copy_cap(card, rules=rules))
        if usable <= 0:
            continue
        if card.super_type == "Signature":
            signature += usable
        else:
            ordinary += usable
    if signature_limit:
        signature = min(signature, signature_limit)
    return ordinary + signature


def assess(
    legend_id: str,
    owned: Mapping[str, int],
    *,
    catalog: Catalog,
    rules: BoundRules,
) -> Feasibility:
    """Can a legal deck for this legend be built from these cards?

    Counting, not searching. Every requirement is reported whether or not it is
    satisfied, so a caller can see how close the pool is and which gap to close first.
    """
    legend = catalog.get(legend_id)
    if legend is None:
        return Feasibility(
            legend_id=legend_id,
            requirements=(
                Requirement(REQ_LEGEND, 1, 0, f"'{legend_id}' is not in the card data"),
            ),
        )

    requirements: list[Requirement] = [
        Requirement(
            REQ_LEGEND, 1, min(1, _owned(owned, legend_id)),
            f"You need a copy of {legend.name}",
        )
    ]

    champions = legal_champions(legend, catalog=catalog, rules=rules)
    owned_champions = [c for c in champions if _owned(owned, c.card_id) > 0]
    if rules.bool_constraint("chosen_champion_required", True):
        requirements.append(
            Requirement(
                REQ_CHAMPION, 1, min(1, len(owned_champions)),
                f"A champion sharing a tag with {legend.name}",
            )
        )

    main_pool = legal_main_pool(legend, catalog=catalog, rules=rules)
    main_needed = rules.int_constraint("main_deck_size_exact", 0)
    if main_needed:
        requirements.append(
            Requirement(
                REQ_MAIN, main_needed,
                _main_capacity(main_pool, owned, rules=rules),
                f"{main_needed} main-deck cards inside {'/'.join(legend.domains) or 'any domain'}",
            )
        )

    rune_needed = rules.int_constraint("rune_count_exact", 0)
    if rune_needed:
        rune_type = rules.str_constraint("rune_card_type", "Rune")
        runes = legal_zone_pool(legend, rune_type, catalog=catalog, rules=rules)
        # Runes carry no per-card copy limit — decks routinely run six of one.
        requirements.append(
            Requirement(
                REQ_RUNES, rune_needed,
                sum(_owned(owned, c.card_id) for c in runes),
                f"{rune_needed} runes in {'/'.join(legend.domains) or 'any domain'}",
            )
        )

    bf_needed = rules.int_constraint("battlefield_count_exact", 0)
    if bf_needed:
        bf_type = rules.str_constraint("battlefield_card_type", "Battlefield")
        battlefields = legal_zone_pool(legend, bf_type, catalog=catalog, rules=rules)
        unique_required = rules.bool_constraint("battlefield_unique_required", False)
        if unique_required:
            available = sum(1 for c in battlefields if _owned(owned, c.card_id) > 0)
            detail = f"{bf_needed} different battlefields"
        else:
            available = sum(_owned(owned, c.card_id) for c in battlefields)
            detail = f"{bf_needed} battlefields"
        requirements.append(Requirement(REQ_BATTLEFIELDS, bf_needed, available, detail))

    return Feasibility(legend_id=legend_id, requirements=tuple(requirements))


@dataclass(frozen=True)
class Preference:
    """How much the meta likes each card for this legend.

    ``play_rate`` ranks which cards to reach for; ``copies`` says how many the field
    actually runs, so a build takes three of a staple and one of a situational card
    rather than maxing everything alphabetically.
    """
    play_rate: Mapping[str, float]
    copies: Mapping[str, int]
    #: How often the field plays two cards together, as a 0..1 conditional probability.
    #:
    #: Optional, and the difference between a deck and a pile. Without it a build is
    #: forty individually popular cards: keep the expensive payoffs after the enabler
    #: that bought them time turned out to be missing, and you have expensive cards and
    #: no plan. With it, each choice is scored against what has already been chosen.
    pair: Callable[[str, str], float] | None = None
    #: Whether a card's usual partners can be fielded at all, 0..1.
    #:
    #: ``pair`` is averaged over everything already chosen, so losing the one card a
    #: card is played for barely moves it: Dazzling Aurora keeps high affinity with the
    #: other seventeen cards in a Jayce list after the Elder Dragon it ramps into is
    #: gone. This is asked once, against everything the player could field, and answers
    #: the different question -- is the reason for playing this card available to them
    #: at all.
    support: Callable[[str, frozenset[str]], float] | None = None

    def rank(self, card_id: str) -> float:
        return float(self.play_rate.get(card_id, 0.0))

    def standing(self, card_id: str, fieldable: frozenset[str]) -> float:
        """Rank, discounted when this card's reason for being played is unavailable."""
        base = self.rank(card_id)
        if self.support is None:
            return base
        return base * self.support(card_id, fieldable)

    def wanted(self, card_id: str, default: int = 3) -> int:
        return max(1, int(self.copies.get(card_id, default)))

    @classmethod
    def empty(cls) -> Preference:
        return cls(play_rate={}, copies={})


#: How much "does this sit with what we have chosen" counts against "how often is this
#: played at all".
#:
#: Judged by ``deck_fidelity`` -- overlap with the real lists of the current era -- on the
#: era-scoped index:
#:
#:   weight        0.75     0.90     0.95     1.00
#:   all legends  0.8800   0.8872   0.8872   0.8872
#:   thin (<20)   0.8168   0.8389   0.8389   0.8389
#:
#: Two things to read off that, and the second corrects what used to be written here.
#:
#: Coherence earns its keep: dropping to 0.75 costs real fidelity, and most of the loss
#: lands on legends with thin evidence.
#:
#: But **0.90, 0.95 and 1.00 are identical, to four decimals, including on the thin
#: legends.** The old comment justified stopping at 0.9 as keeping "a real popularity
#: term, which matters for a legend with few published decks where the pairing counts are
#: thin enough to be noise". That is not what happens. Above 0.9 the pairing term so
#: dominates that the remaining popularity weight never flips a pick, so the term the
#: comment was protecting does nothing at all. 0.9 is kept because it is measured equal to
#: the alternatives and changing a constant for no measured gain is churn -- not because
#: the popularity term is doing the work the old note claimed.
#:
#: (The figures that used to sit here -- an orphan-share sweep -- predated both era
#: scoping and the removal of the archetype steer, and no longer described the builder
#: they were annotating.)
COHERENCE_WEIGHT = 0.9


def _fill_by_affinity(
    candidates: Sequence[Card],
    take,
    pref: Preference,
    *,
    chosen: list[str],
    filled,
    target: int,
) -> None:
    """Pick each card against the deck so far, not against the format in general.

    Greedy, and re-scored after every addition, which is the whole point: the value of
    a card depends on what is already in the deck. Affinity is accumulated as a running
    sum per candidate so a re-score costs one dictionary lookup per card rather than a
    fresh pass over the deck.
    """
    assert pref.pair is not None
    # Judged against everything they could field, not against the partial deck. Mid-build
    # a partner is "absent" simply because it has not been picked yet; what matters is
    # whether it can ever arrive.
    fieldable = frozenset({c.card_id for c in candidates} | set(chosen))
    running: dict[str, float] = {c.card_id: 0.0 for c in candidates}
    for card_id in chosen:
        for candidate in candidates:
            running[candidate.card_id] += pref.pair(candidate.card_id, card_id)

    remaining = list(candidates)
    while remaining and (not target or filled() < target):
        partners = max(1, len(chosen))
        best = max(
            remaining,
            key=lambda c: (
                (1.0 - COHERENCE_WEIGHT) * pref.standing(c.card_id, fieldable)
                + COHERENCE_WEIGHT * (running[c.card_id] / partners),
                -0.0,
                c.name,
            ),
        )
        remaining.remove(best)
        if take(best, pref.wanted(best.card_id)) <= 0:
            continue
        chosen.append(best.card_id)
        for candidate in remaining:
            running[candidate.card_id] += pref.pair(candidate.card_id, best.card_id)


def build(
    legend_id: str,
    owned: Mapping[str, int],
    *,
    catalog: Catalog,
    rules: BoundRules,
    preference: Preference | None = None,
    name: str = "",
) -> Deck | None:
    """Build the best legal deck this collection supports for this legend.

    Returns None when no legal deck is possible — :func:`assess` explains why.
    """
    feasibility = assess(legend_id, owned, catalog=catalog, rules=rules)
    if not feasibility.ok:
        return None

    legend = catalog.get(legend_id)
    assert legend is not None  # assess() would have failed otherwise
    pref = preference or Preference.empty()

    # -- champion: the most-played one the collection can field --------------
    champions = [
        c
        for c in legal_champions(legend, catalog=catalog, rules=rules)
        if _owned(owned, c.card_id) > 0
    ]
    champion = max(champions, key=lambda c: (pref.rank(c.card_id), c.name), default=None)

    # -- main deck ------------------------------------------------------------
    main_needed = rules.int_constraint("main_deck_size_exact", 0)
    signature_limit = rules.int_constraint("signature_max_total", 0)
    main: dict[str, int] = {}
    signatures_used = 0

    def take(card: Card, count: int) -> int:
        """Add up to `count` copies, respecting every cap. Returns how many were added."""
        nonlocal signatures_used
        room = main_needed - sum(main.values()) if main_needed else count
        allowed = min(
            count,
            room,
            copy_cap(card, rules=rules) - main.get(card.card_id, 0),
            _owned(owned, card.card_id) - main.get(card.card_id, 0),
        )
        if card.super_type == "Signature" and signature_limit:
            allowed = min(allowed, signature_limit - signatures_used)
        if allowed <= 0:
            return 0
        main[card.card_id] = main.get(card.card_id, 0) + allowed
        if card.super_type == "Signature":
            signatures_used += allowed
        return allowed

    # The nominated champion has to be in the main deck, so it goes in first.
    if champion is not None:
        take(champion, pref.wanted(champion.card_id))

    candidates = [
        c
        for c in legal_main_pool(legend, catalog=catalog, rules=rules)
        if _owned(owned, c.card_id) > 0
    ]
    # Most-played first; name breaks ties so a build is reproducible.
    candidates.sort(key=lambda c: (-pref.rank(c.card_id), c.name))

    if pref.pair is None:
        # No pairing signal: fall back to straight popularity. First pass takes what the
        # field runs of each card, second tops up when the collection is thin.
        for card in candidates:
            if main_needed and sum(main.values()) >= main_needed:
                break
            take(card, pref.wanted(card.card_id))
    else:
        _fill_by_affinity(
            candidates, take, pref,
            chosen=list(main),
            filled=lambda: sum(main.values()),
            target=main_needed,
        )

    # Whatever the first pass left, fill from the ranked list. The guarantee is a legal
    # forty; coherence is a preference and must never cost a deck.
    for card in candidates:
        if main_needed and sum(main.values()) >= main_needed:
            break
        take(card, copy_cap(card, rules=rules))

    if main_needed and sum(main.values()) != main_needed:
        return None  # assess() said this was possible; the pool disagreed

    # -- runes ----------------------------------------------------------------
    runes = _fill_flat(
        legal_zone_pool(
            legend, rules.str_constraint("rune_card_type", "Rune"),
            catalog=catalog, rules=rules,
        ),
        owned, rules.int_constraint("rune_count_exact", 0), pref,
    )

    # -- battlefields ---------------------------------------------------------
    bf_pool = legal_zone_pool(
        legend, rules.str_constraint("battlefield_card_type", "Battlefield"),
        catalog=catalog, rules=rules,
    )
    bf_needed = rules.int_constraint("battlefield_count_exact", 0)
    battlefields: list[str] = []
    if bf_needed:
        owned_bf = [c for c in bf_pool if _owned(owned, c.card_id) > 0]
        owned_bf.sort(key=lambda c: (-pref.rank(c.card_id), c.name))
        if rules.bool_constraint("battlefield_unique_required", False):
            battlefields = [c.card_id for c in owned_bf[:bf_needed]]
        else:
            for card in owned_bf:
                while len(battlefields) < bf_needed and (
                    battlefields.count(card.card_id) < _owned(owned, card.card_id)
                ):
                    battlefields.append(card.card_id)
        if len(battlefields) != bf_needed:
            return None

    return Deck.make(
        name=name or f"{legend.name} — built from your collection",
        format=rules.format_name,
        legend_id=legend_id,
        champion_id=champion.card_id if champion else "",
        main=main,
        runes=runes,
        battlefields=battlefields,
        sideboard={},
    )


def _fill_flat(
    pool: list[Card], owned: Mapping[str, int], needed: int, preference: Preference
) -> dict[str, int]:
    """Fill a zone with no per-card copy limit, most-played first."""
    if not needed:
        return {}
    ordered = sorted(
        (c for c in pool if _owned(owned, c.card_id) > 0),
        key=lambda c: (-preference.rank(c.card_id), c.name),
    )
    out: dict[str, int] = {}
    remaining = needed
    for card in ordered:
        if remaining <= 0:
            break
        take = min(remaining, _owned(owned, card.card_id))
        if take > 0:
            out[card.card_id] = take
            remaining -= take
    return out
