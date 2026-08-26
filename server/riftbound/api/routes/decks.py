"""Deck building: validate, save, load, delete.

Validation always reports *both* legality (rules) and coverage (availability), so the
UI can distinguish "this deck is illegal" from "this deck is legal but you're missing
four cards" -- two different problems that v2 conflated.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response

from ...config import ConfigError
from ...domain.availability import deck_coverage
from ...domain.deck import Deck
from ...domain.validator import validate
from ...services import Services, get_services
from ..identity import Identity, current_identity
from ..schemas import DeckPayload, DeckSummaryView, DeckView, ValidationView
from ..views import deck_dict, validation_view

router = APIRouter(prefix="/api/decks", tags=["decks"])


def _to_deck(payload: DeckPayload) -> Deck:
    return Deck.make(
        name=payload.name,
        format=payload.format,
        legend_id=payload.legend_id,
        champion_id=payload.champion_id,
        main=payload.main,
        runes=payload.runes,
        battlefields=payload.battlefields,
        sideboard=payload.sideboard,
    )


def _validate(deck: Deck, services: Services, user_id: str) -> ValidationView:
    try:
        rules = services.rules_for(deck.format)
    except ConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    profile = services.availability.load(user_id=user_id)
    result = validate(deck, rules=rules, catalog=services.catalog)
    counts = dict(deck.main)
    for card_id in deck.battlefields:
        counts[card_id] = counts.get(card_id, 0) + 1
    for card_id, qty in deck.runes.items():
        counts[card_id] = counts.get(card_id, 0) + qty
    coverage = deck_coverage(counts, profile=profile, catalog=services.catalog)
    return validation_view(result, coverage, services.catalog)


@router.post("/validate", response_model=ValidationView)
def validate_deck(
    payload: DeckPayload,
    services: Services = Depends(get_services),
    identity: Identity = Depends(current_identity),
) -> ValidationView:
    return _validate(_to_deck(payload), services, identity.user_id)


@router.get("", response_model=list[DeckSummaryView])
def list_decks(
    services: Services = Depends(get_services),
    identity: Identity = Depends(current_identity),
) -> list[DeckSummaryView]:
    return [
        DeckSummaryView(
            deck_id=s.deck_id, name=s.name, format=s.format, legend_id=s.legend_id,
            champion_id=s.champion_id, main_total=s.main_total,
            created_at=s.created_at, updated_at=s.updated_at,
        )
        for s in services.decks.list(user_id=identity.user_id)
    ]


@router.post("", response_model=DeckView, status_code=201)
def create_deck(
    payload: DeckPayload,
    services: Services = Depends(get_services),
    identity: Identity = Depends(current_identity),
) -> DeckView:
    deck = _to_deck(payload)
    deck_id = services.decks.save(deck, user_id=identity.user_id)
    return DeckView(
        deck_id=deck_id,
        deck=deck_dict(deck),
        validation=_validate(deck, services, identity.user_id),
    )


@router.get("/{deck_id}", response_model=DeckView)
def get_deck(
    deck_id: str,
    services: Services = Depends(get_services),
    identity: Identity = Depends(current_identity),
) -> DeckView:
    deck = services.decks.get(deck_id, user_id=identity.user_id)
    if deck is None:
        raise HTTPException(status_code=404, detail="Deck not found.")
    return DeckView(
        deck_id=deck_id,
        deck=deck_dict(deck),
        validation=_validate(deck, services, identity.user_id),
    )


@router.put("/{deck_id}", response_model=DeckView)
def update_deck(
    deck_id: str,
    payload: DeckPayload,
    services: Services = Depends(get_services),
    identity: Identity = Depends(current_identity),
) -> DeckView:
    if services.decks.get(deck_id, user_id=identity.user_id) is None:
        raise HTTPException(status_code=404, detail="Deck not found.")
    deck = _to_deck(payload)
    services.decks.save(deck, user_id=identity.user_id, deck_id=deck_id)
    return DeckView(
        deck_id=deck_id,
        deck=deck_dict(deck),
        validation=_validate(deck, services, identity.user_id),
    )


@router.delete("/{deck_id}", status_code=204, response_class=Response)
def delete_deck(
    deck_id: str,
    services: Services = Depends(get_services),
    identity: Identity = Depends(current_identity),
) -> Response:
    if not services.decks.delete(deck_id, user_id=identity.user_id):
        raise HTTPException(status_code=404, detail="Deck not found.")
    return Response(status_code=204)
