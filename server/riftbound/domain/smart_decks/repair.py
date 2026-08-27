"""Filling a deck's holes from cards the player owns.

Two products with the same shape and different promises. A **conservative** repair draws
only from the deck's own family, so the result is still recognisably the deck that won.
A **free** repair will use any legal owned card: it answers far more often, and what
comes out may share little with what was proposed. The caller has to label them, so they
are returned separately rather than ranked.

Whatever comes out is validated before it is returned. Filling holes by count is not the
same as producing a legal deck, and a deck labelled "not legal" that the player is
nonetheless invited to save is worse than no answer.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..cards import Catalog
from ..deck import Deck
from ..deck_builder import (
    legal_zone_pool,
)
from ..legend_index import LegendProfile, substitutes
from ..rules import BoundRules
from ..validator import validate
from .knowledge import Knowledge, gaps_for

#: A deck this many copies short is repaired rather than discarded.
REPAIRABLE_COPIES = 12








# -- knowledge ----------------------------------------------------------------






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
    from ..deck_builder import legal_main_pool

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
    if card.unlimited_copies:
        # The card's own text outranks the format's limit.
        return rules.int_constraint("main_deck_size_exact", 0) or 99
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
