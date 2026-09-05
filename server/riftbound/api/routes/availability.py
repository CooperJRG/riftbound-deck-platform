"""The availability profile: the player's answer to "what can you actually field?"

The exclusion endpoints are the low-friction path. ``POST /api/availability/exclude``
takes a card the player says they don't have and switches the profile into exclusion
mode on the spot, so the first thing a new player does can be "I don't have Seal of
Discord" -- no collection, no setup screen.
"""

from __future__ import annotations

from dataclasses import replace

from fastapi import APIRouter, Depends, HTTPException

from ...domain.availability import (
    MODE_COLLECTION,
    MODE_EXCLUSION,
    RULE_KINDS,
    AvailabilityProfile,
    ExclusionRule,
    OwnedRule,
)
from ...services import Services, get_services
from ..identity import Identity, current_identity
from ..schemas import AvailabilityUpdate, AvailabilityView, ForgetResult
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


@router.delete("/collection", response_model=ForgetResult)
def forget_collection(
    services: Services = Depends(get_services),
    identity: Identity = Depends(current_identity),
) -> ForgetResult:
    """Erase everything recorded about what this user owns.

    Both halves, deliberately. The collection rows are the obvious ones, but a wizard
    session's answers say what somebody owns just as plainly -- three rounds pin down
    roughly 75 cards -- so erasing one and leaving the other would be a privacy control
    that only looks like one.

    The wizard offers to write what a session learned into the collection, which is by
    some distance the fastest way to record one. A one-way door into that is not a fair
    trade for the convenience, so this is the way back out.

    Collection mode is switched to open on the way, because a collection-mode profile
    standing on an empty collection tells the player every card in the game is missing --
    which is true, and useless. Open is the honest posture once they have told us
    nothing: assume they can get anything, rather than that they have nothing.
    """
    rows = services.collections.clear(user_id=identity.user_id)
    sessions = services.smart_decks.clear_all(user_id=identity.user_id)

    profile = _load(services, identity.user_id)
    profile = replace(
        profile,
        mode="open" if profile.mode == MODE_COLLECTION else profile.mode,
        owned={},
        owned_rules=(),
    )
    services.availability.save(profile, user_id=identity.user_id)

    return ForgetResult(
        collection_rows=rows,
        sessions=sessions,
        availability=availability_view(profile, services.catalog),
    )


@router.put("", response_model=AvailabilityView)
def set_availability(
    update: AvailabilityUpdate,
    services: Services = Depends(get_services),
    identity: Identity = Depends(current_identity),
) -> AvailabilityView:
    try:
        mode = update.validated_mode()
        rules = update.validated_rules()
        owned_rules = update.validated_owned_rules()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    unknown = [cid for cid in update.excluded_card_ids if services.catalog.get(cid) is None]
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown card id(s): {', '.join(sorted(unknown)[:5])}",
        )
    # Mode chooses which settings apply. It must not erase the inactive settings
    # the client carries across a mode switch.
    profile = AvailabilityProfile(
        mode=mode,
        owned=services.collections.owned_by_card(user_id=identity.user_id, include_zero=True),
        excluded_cards=frozenset(update.excluded_card_ids),
        exclusion_rules=tuple(ExclusionRule(kind=r.kind, value=r.value) for r in rules),
        owned_rules=tuple(OwnedRule(kind=r.kind, value=r.value) for r in owned_rules),
        strict=update.strict,
        penalty=update.penalty,
    )

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
    profile = replace(
        current,
        mode=MODE_EXCLUSION,
        excluded_cards=current.excluded_cards | {card.card_id},
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
    profile = replace(
        current,
        mode=MODE_EXCLUSION,
        excluded_cards=current.excluded_cards - {card_id.strip().lower()},
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
