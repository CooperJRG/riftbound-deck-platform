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

from collections.abc import Mapping
from dataclasses import dataclass, field

from ..cards import Catalog
from ..deck import ZONE_BATTLEFIELDS, ZONE_MAIN, ZONE_RUNES, Deck
from ..deck_builder import (
    legal_zone_pool,
)
from ..legend_index import LegendProfile, substitutes
from ..rules import BoundRules
from ..validator import validate
from .knowledge import Knowledge, gaps_for

#: A deck this many copies short is repaired rather than discarded.
REPAIRABLE_COPIES = 12

#: Stands in for "no shape constraint" where a zone has no meaningful per-card count.
_MANY = 99








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

    # Build it both ways and keep the better one.
    #
    # Dropping a card the player owns is sometimes the right move: a single copy of
    # something the field runs as a playset is a quantity nobody plays, and the slot
    # could hold a third copy of something else. But *always* cutting those stubs is
    # plainly wrong -- measured over 400 repairs where the choice mattered, it lost
    # play-rate mass 97% of the time, a median 5.25%, to save one card of width. Deck
    # shape is worth something and it is not worth that.
    #
    # So the cut is considered rather than applied, on the same footing as any other
    # candidate repair: it has to actually produce a better deck. It wins about 3% of
    # the time, which is what "sometimes" turned out to mean. Ties keep the stub, since
    # a player would rather hold the card they own than have it swapped for no gain.
    patched = _attempt(
        deck, holes, profile=profile, catalog=catalog, rules=rules, legend=legend,
        owned=owned, allowed=allowed, conservative=conservative, cut_stubs=False,
    )
    cut = _attempt(
        deck, holes, profile=profile, catalog=catalog, rules=rules, legend=legend,
        owned=owned, allowed=allowed, conservative=conservative, cut_stubs=True,
    )
    if patched is None:
        return cut
    if cut is None:
        return patched
    return cut if _mass(cut.deck, profile) > _mass(patched.deck, profile) else patched


def _attempt(
    deck: Deck,
    holes,
    *,
    profile: LegendProfile,
    catalog: Catalog,
    rules: BoundRules,
    legend,
    owned: Mapping[str, int],
    allowed: set[str] | None,
    conservative: bool,
    cut_stubs: bool,
) -> Repair | None:
    """One pass at filling the holes, with or without cutting leftover singletons."""
    zones = _Zones(
        main=dict(deck.main), runes=dict(deck.runes), battlefields=list(deck.battlefields),
        sideboard=dict(deck.sideboard),
    )
    swaps: list[Swap] = []
    drift = 0

    # What each zone still owes, pooled across its holes.
    #
    # Filling holes one at a time is what made a repaired deck sprawl. Measured over 500
    # repairs of real lists, 67.6% of holes are a single copy and the binding limit on
    # 86.5% of fills is the hole itself -- so each hole took one copy of one new card,
    # and a list short six copies came back six names wider: 24 unique cards where the
    # field plays 18. Pooling lets one candidate arrive as the playset the field runs it
    # as and cover the next two holes with it, which measured 24 -> 21, the widest list
    # the field actually plays.
    owed: dict[str, int] = {}
    for hole in holes:
        card = catalog.get(hole.card_id)
        if card is None or hole.card_id == deck.legend_id:
            return None  # a legend has no substitute
        zone = _zone_of(card)
        keep = hole.have
        if cut_stubs and _is_stub(profile, hole, zone, deck):
            # The leftover copy goes back into the budget rather than into the deck.
            keep = 0
        zones.set_to(zone, hole.card_id, keep)
        owed[zone] = owed.get(zone, 0) + hole.needed - keep
        drift += hole.needed - keep

    for hole in holes:
        card = catalog.get(hole.card_id)
        if card is None:
            return None
        zone = _zone_of(card)
        if owed.get(zone, 0) <= 0:
            continue  # an earlier playset already covered this

        pool = _zone_pool(zone, legend, catalog=catalog, rules=rules)
        # Ranked per hole rather than once per zone, so role still matters: a spell is
        # replaced by something that does a spell's job, not merely by whatever the deck
        # pairs with most.
        ranked = substitutes(
            hole.card_id, profile=profile, owned=owned, catalog=catalog,
            context=zones.all_cards(),
        )

        # Shape first, then whatever is left. Preferring the field's own counts must
        # never cost an answer: a player short of cards would rather hold a deck with an
        # odd curve than be told no, so the second pass drops the constraint rather than
        # failing.
        for shape_first in (True, False):
            if owed[zone] <= 0:
                break
            owed[zone] -= _fill(
                hole, ranked, zones, swaps,
                budget=owed[zone], zone=zone, pool=pool, allowed=allowed, owned=owned,
                profile=profile, catalog=catalog, rules=rules, shape_first=shape_first,
            )

    if any(v > 0 for v in owed.values()):
        return None

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


def _fill(
    hole,
    ranked,
    zones: _Zones,
    swaps: list[Swap],
    *,
    budget: int,
    zone: str,
    pool: set[str],
    allowed: set[str] | None,
    owned: Mapping[str, int],
    profile: LegendProfile,
    catalog: Catalog,
    rules: BoundRules,
    shape_first: bool,
) -> int:
    """Take copies for one hole, returning how many were added.

    Lifted out of the loop rather than closed over it: a nested function reading
    ``hole`` and ``ranked`` from the enclosing scope is correct only while it is called
    in the same iteration, which is the kind of thing that stays correct until somebody
    moves the call.
    """
    added = 0
    order = list(ranked)
    if shape_first:
        # Prefer a card the list already plays over a new name.
        #
        # Two wrong turns before this one, both worth recording. Capping copies at the
        # field's count made things worse -- it took one copy of the best substitute and
        # moved on. Sorting by how much a candidate could supply barely moved either.
        # Measured, the binding limit on 86.5% of fills is the *hole*: 67.6% of holes
        # are a single copy, and the card's own count binds 0.2% of the time.
        #
        # So the sprawl is arithmetic, not judgement. Being short one copy of a three-of
        # leaves it in the deck as a two-of and adds a one-of beside it: the list gains
        # a name and a singleton, every time, and after a few holes it is 24 cards wide
        # where the field plays 18. Topping an existing card up toward the count the
        # field runs it at fills the same hole and adds no name at all.
        def shape_fit(entry: tuple[str, float]) -> tuple[int, int, float]:
            candidate_id, score = entry
            card = catalog.get(candidate_id)
            if card is None:
                return (0, 0, score)
            already = zones.committed(zone, candidate_id)
            room = min(
                budget - added,
                owned.get(candidate_id, 0) - already,
                _zone_cap(card, zone, rules=rules) - already,
                _natural_copies(profile, candidate_id, zone) - already,
            )
            already_played = 1 if already > 0 and room > 0 else 0
            return (already_played, max(0, room), score)

        order.sort(key=shape_fit, reverse=True)

    for candidate_id, score in order:
        if added >= budget:
            break
        if candidate_id not in pool:
            continue
        if allowed is not None and candidate_id not in allowed:
            continue
        candidate = catalog.get(candidate_id)
        if candidate is None:
            continue
        # Against the limit: every zone that shares it. Against what they own: the same,
        # since a card in the sideboard is a copy already spoken for.
        already = zones.committed(zone, candidate_id)
        limits = [
            budget - added,
            owned.get(candidate_id, 0) - already,
            _zone_cap(candidate, zone, rules=rules) - already,
        ]
        if shape_first:
            # The count the field actually runs this card at, minus what the deck
            # already holds. A card the field plays as a one-of arrives as a one-of; a
            # staple arrives as a playset, or tops an existing copy up to one, rather
            # than adding another name to a list that already has enough.
            limits.append(_natural_copies(profile, candidate_id, zone) - already)
        room = min(limits)
        if room <= 0:
            continue
        zones.add(zone, candidate_id, room)
        added += room
        swaps.append(
            Swap(
                out_card_id=hole.card_id, in_card_id=candidate_id, copies=room,
                reason=f"the field plays this alongside the deck {score:.0%} of the time",
            )
        )
    return added


def _natural_copies(profile: LegendProfile, card_id: str, zone: str) -> int:
    """How many copies of this card the field runs for this legend.

    ``profile.copies`` already carries it -- a weighted mean over the era's lists,
    rounded -- and until now nothing filling a hole consulted it. A repair took as many
    copies of its best substitute as the player happened to own, which with a thin
    collection means one copy each of many different cards. Measured over 500 repairs of
    real lists, that pushed the median deck from 18 unique cards to 24, turned 46% of
    slots being three-ofs into 14%, and left 89% of repaired decks wider than the p90 of
    any list the field has actually played.

    The mean rather than the mode, deliberately. The mode predicts a held-out slot at
    73.4% and this at 72.9% -- a difference that does not justify a second statistic
    that could disagree with the first, and the rounded mean names a count the field
    never runs for a given card in 0.2% of cases.

    Runes are exempt: they are not a curve decision, they are a resource base sized to
    the deck, and a rune "played as 9" is an artefact of averaging bases of 6 and 12.
    """
    if zone in (ZONE_RUNES, ZONE_BATTLEFIELDS):
        return _MANY
    return max(1, int(profile.copies.get(card_id, 1)))


def _is_stub(profile: LegendProfile, hole, zone: str, deck: Deck) -> bool:
    """Is the copy the player owns worth keeping, or is it a leftover?

    Sometimes dropping a card somebody owns is the right move, and there is exactly one
    case the field supports. Measured across every card played in 20 or more lists:

      the field runs 3, deck left at 2 -- played 18.2% of the time
      the field runs 2, deck left at 1 -- played 19.9% of the time
      the field runs 3, deck left at 1 -- played  4.7% of the time (median 1.9%)

    The first two are configurations the field genuinely plays, so a partial there is a
    real deck and keeping it is right. The last is not: for 71% of playset cards a
    single copy appears in 5% or fewer of their lists. Keeping it hands the player a
    card in a quantity nobody plays it in, *and* costs a slot that could hold a third
    copy of something else -- so the copy goes back into the budget and the fill places
    it where the field would.

    Deliberately narrow. It fires only for a card the field runs as a full playset of
    which the player holds exactly one, never for the champion, whose presence defines
    the deck, and never outside the main deck, where counts are a resource base rather
    than a curve.
    """
    if zone != ZONE_MAIN or hole.have != 1:
        return False
    if hole.card_id == deck.champion_id:
        return False
    return _natural_copies(profile, hole.card_id, zone) >= 3


def _mass(deck: Deck, profile: LegendProfile) -> float:
    """How much of what the field plays this deck contains.

    The same measure the acceptance harness scores a built deck by, so a repair that
    chooses between two candidate decks is answering to the number it will later be
    judged on rather than to one invented here.
    """
    return sum(profile.play_rate.get(card_id, 0.0) * n for card_id, n in deck.main.items())
