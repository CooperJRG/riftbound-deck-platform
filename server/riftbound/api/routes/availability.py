"""The availability profile: the player's answer to "what can you actually field?"

The exclusion endpoints are the low-friction path. ``POST /api/availability/exclude``
takes a card the player says they don't have and switches the profile into exclusion
mode on the spot, so the first thing a new player does can be "I don't have Seal of
Discord" -- no collection, no setup screen.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ...domain.availability import (
    AvailabilityProfile,
    ExclusionRule,
    MODE_COLLECTION,
    MODE_EXCLUSION,
    RULE_KINDS,
)
from ...services import Services, get_services
from ..identity import Identity, current_identity
from ..schemas import AvailabilityUpdate, AvailabilityView
from ..views import availability_view

router = APIRouter(prefix="/api/availability", tags=["availability"])


def _load(services: Services, user_id: str) -> AvailabilityProfile:
    return services.availability.load(user_id=user_id)


@router.get("", response_model=AvailabilityView)
def get_availability(
    services: Services = Depends(get_services),
    identity: Identity = Depends(current_identity),
) -> AvailabilityView:
    return availability_view(_load(services, identity.user_id), services.catalog)


@router.put("", response_model=AvailabilityView)
def set_availability(
    update: AvailabilityUpdate,
    services: Services = Depends(get_services),
    identity: Identity = Depends(current_identity),
) -> AvailabilityView:
    try:
        mode = update.validated_mode()
        rules = update.validated_rules()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if mode == MODE_COLLECTION:
        profile = AvailabilityProfile.from_collection(
            services.collections.owned_by_card(user_id=identity.user_id),
            strict=update.strict,
            penalty=update.penalty,
        )
    elif mode == MODE_EXCLUSION:
        unknown = [
            cid for cid in update.excluded_card_ids if services.catalog.get(cid) is None
        ]
        if unknown:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown card id(s): {', '.join(sorted(unknown)[:5])}",
            )
        profile = AvailabilityProfile.from_exclusions(
            card_ids=update.excluded_card_ids,
            rules=[ExclusionRule(kind=r.kind, value=r.value) for r in rules],
            strict=update.strict,
            penalty=update.penalty,
        )
    else:
        profile = AvailabilityProfile.open_profile()

    services.availability.save(profile, user_id=identity.user_id)
    return availability_view(profile, services.catalog)


@router.post("/exclude/{card_id}", response_model=AvailabilityView)
def exclude_card(
    card_id: str,
    services: Services = Depends(get_services),
    identity: Identity = Depends(current_identity),
) -> AvailabilityView:
    """"I don't have this one." Switches into exclusion mode if needed."""
    card = services.catalog.get(card_id)
    if card is None:
        raise HTTPException(status_code=404, detail=f"No card {card_id!r}.")

    current = _load(services, identity.user_id)
    profile = AvailabilityProfile.from_exclusions(
        card_ids=set(current.excluded_cards) | {card.card_id},
        rules=current.exclusion_rules,
        strict=current.strict if current.mode == MODE_EXCLUSION else False,
        penalty=current.penalty,
    )
    services.availability.save(profile, user_id=identity.user_id)
    return availability_view(profile, services.catalog)


@router.delete("/exclude/{card_id}", response_model=AvailabilityView)
def unexclude_card(
    card_id: str,
    services: Services = Depends(get_services),
    identity: Identity = Depends(current_identity),
) -> AvailabilityView:
    current = _load(services, identity.user_id)
    profile = AvailabilityProfile.from_exclusions(
        card_ids=set(current.excluded_cards) - {card_id.strip().lower()},
        rules=current.exclusion_rules,
        strict=current.strict,
        penalty=current.penalty,
    )
    services.availability.save(profile, user_id=identity.user_id)
    return availability_view(profile, services.catalog)


@router.get("/rule-kinds")
def rule_kinds(services: Services = Depends(get_services)) -> dict:
    """Available one-click exclusion rules, with the values present in this bundle."""
    catalog = services.catalog
    return {
        "kinds": list(RULE_KINDS),
        "values": {
            "rarity": sorted({c.rarity for c in catalog if c.rarity}),
            "set": sorted({s for c in catalog for s in c.set_codes}),
            "super_type": sorted({c.super_type for c in catalog if c.super_type}),
            "promo_only": [],
        },
    }
