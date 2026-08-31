"""Small, honest signals for a deck that is still being built.

This deliberately compares published *lists*, not matchups.  None of our sources
records opponents, so similarity may describe the shape of the field but must never be
presented as evidence about what a deck beats.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from .cards import Catalog
from .deck import Deck
from .deck_fidelity import jaccard
from .legend_index import CLUSTER_THRESHOLD
from .meta import MetaDeck, archetype_id_for
from .rules import BoundRules

#: Used only when no format rules are supplied. Every call site in this codebase has
#: a format's rules to hand; this exists so the function still degrades sensibly if
#: one is ever missing, rather than raising.
DEFAULT_MAIN_DECK_SIZE = 40


@dataclass(frozen=True)
class FieldMatch:
    available: bool = False
    archetype_id: str = ""
    name: str = ""
    sample_decks: int = 0
    tournament_decks: int = 0
    similarity: float = 0.0
    threshold: float = CLUSTER_THRESHOLD
    chosen_cards: int = 0
    matched_cards: int = 0
    copy_changes: int = 0
    reference_deck_id: str = ""
    reference_deck_name: str = ""
    summary: str = "Choose a legend and add cards to compare this list with the published field."


def _copy_changes(left: Mapping[str, int], right: Mapping[str, int]) -> int:
    """Fewest copy slots that must change to turn one list into the other."""
    ids = set(left) | set(right)
    removed = sum(max(0, left.get(card_id, 0) - right.get(card_id, 0)) for card_id in ids)
    added = sum(max(0, right.get(card_id, 0) - left.get(card_id, 0)) for card_id in ids)
    return max(removed, added)


def nearest_field_match(
    deck: Deck,
    published: Iterable[MetaDeck],
    catalog: Catalog,
    scores: Mapping[str, float] | None = None,
    rules: BoundRules | None = None,
) -> FieldMatch:
    """The nearest complete published list for this identity.

    Jaccard is the same measured card-family signal used by the legend index.  Quality
    is only a tie-break, so a popular but unrelated list cannot outrank a closer one.
    """
    chosen = set(deck.main)
    if not deck.legend_id or not chosen:
        return FieldMatch(chosen_cards=len(chosen))

    candidates = [
        row for row in published
        if row.is_complete
        and row.deck.legend_id == deck.legend_id
        and (not deck.champion_id or row.deck.champion_id == deck.champion_id)
    ]
    if not candidates:
        return FieldMatch(
            chosen_cards=len(chosen),
            summary="No complete published lists match this legend and champion yet.",
        )

    score_map = scores or {}
    nearest = max(
        candidates,
        key=lambda row: (
            jaccard(chosen, row.deck.main),
            score_map.get(row.deck_id, 0.0),
            row.deck_id,
        ),
    )
    reference_cards = set(nearest.deck.main)
    similarity = jaccard(chosen, reference_cards)
    matched = len(chosen & reference_cards)
    archetype_id = archetype_id_for(nearest.deck.legend_id, nearest.deck.champion_id)
    family = [row for row in candidates if row.archetype_id == archetype_id]
    legend = catalog.get(nearest.deck.legend_id)
    champion = catalog.get(nearest.deck.champion_id)
    name = " · ".join(
        value for value in (
            legend.name if legend else nearest.deck.legend_id,
            champion.name if champion else nearest.deck.champion_id,
        ) if value
    )
    main_deck_size = (
        rules.int_constraint("main_deck_size_exact", DEFAULT_MAIN_DECK_SIZE)
        if rules is not None
        else DEFAULT_MAIN_DECK_SIZE
    )
    if deck.main_total < main_deck_size:
        summary = (
            f"{matched} of {len(chosen)} chosen card names appear in the closest "
            f"published {name or 'archetype'} list."
        )
    else:
        summary = (
            f"{similarity:.0%} card-family overlap with the closest published "
            f"{name or 'archetype'} list."
        )
    return FieldMatch(
        available=True,
        archetype_id=archetype_id,
        name=name,
        sample_decks=len(family),
        tournament_decks=sum(1 for row in family if row.provenance.is_tournament),
        similarity=round(similarity, 4),
        chosen_cards=len(chosen),
        matched_cards=matched,
        copy_changes=_copy_changes(deck.main, nearest.deck.main),
        reference_deck_id=nearest.deck_id,
        reference_deck_name=nearest.deck.name,
        summary=summary,
    )
