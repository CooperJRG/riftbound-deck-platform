"""Card browsing, always answered through the active availability profile.

Every card carries its resolved weight, so the UI can sort and shade by "can I
actually field this" without knowing whether the player is in collection or exclusion
mode.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from ...domain.cards import RARITY_ORDER
from ...domain.ids import search_key
from ...services import Services, get_services
from ..identity import Identity, current_identity
from ..schemas import CardPage, CardView
from ..views import card_availability_view, card_view

router = APIRouter(prefix="/api/cards", tags=["cards"])


@router.get("", response_model=CardPage)
def list_cards(
    q: str = Query(default="", max_length=120, description="name or effect text search"),
    card_type: str = Query(default="", alias="cardType", max_length=40),
    domain: str = Query(default="", max_length=20),
    set_code: str = Query(default="", alias="setCode", max_length=8),
    rarity: str = Query(default="", max_length=20),
    available_only: bool = Query(default=False, alias="availableOnly"),
    sort: str = Query(default="name", pattern="^(name|cost|availability)$"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=60, ge=1, le=500),
    services: Services = Depends(get_services),
    identity: Identity = Depends(current_identity),
) -> CardPage:
    profile = services.availability.load(user_id=identity.user_id)
    needle = search_key(q)

    rows = []
    for card in services.catalog:
        if card_type and card.card_type != card_type:
            continue
        if domain and domain not in card.domains:
            continue
        if set_code and set_code.upper() not in card.set_codes:
            continue
        if rarity and card.rarity != rarity:
            continue
        if needle and needle not in search_key(card.name) and needle not in search_key(card.effect):
            continue
        state = profile.resolve(card)
        if available_only and not state.available:
            continue
        rows.append((card, state))

    if sort == "cost":
        rows.sort(key=lambda r: (r[0].cost if r[0].cost is not None else 99, r[0].name.casefold()))
    elif sort == "availability":
        rows.sort(key=lambda r: (-r[1].weight, r[0].name.casefold()))
    else:
        rows.sort(key=lambda r: r[0].name.casefold())

    window = rows[offset : offset + limit]
    return CardPage(
        total=len(rows),
        offset=offset,
        limit=limit,
        cards=[card_availability_view(card, state) for card, state in window],
    )


@router.get("/facets")
def card_facets(services: Services = Depends(get_services)) -> dict:
    """Filter values derived from the bundle, so a new set appears without a code change."""
    catalog = services.catalog
    return {
        "cardTypes": sorted({c.card_type for c in catalog if c.card_type}),
        "superTypes": sorted({c.super_type for c in catalog if c.super_type}),
        "domains": sorted({d for c in catalog for d in c.domains}),
        "setCodes": sorted({s for c in catalog for s in c.set_codes}),
        "rarities": [r for r in RARITY_ORDER if any(c.rarity == r for c in catalog)],
    }


@router.get("/{card_id}", response_model=CardView)
def get_card(card_id: str, services: Services = Depends(get_services)) -> CardView:
    card = services.catalog.get(card_id)
    if card is None:
        raise HTTPException(status_code=404, detail=f"No card {card_id!r} in the current bundle.")
    return card_view(card)
