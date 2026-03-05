from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth.dependencies import bootstrap_profile_from_claims, require_user, require_valid_token
from app.auth.verifier import TokenClaims
from app.core.services import AppServices, get_services
from app.domain.models import FeatureFlags, MeResponse

router = APIRouter(prefix="/api/me", tags=["me"])


def _me_response(services: AppServices, *, user) -> MeResponse:
    return MeResponse(
        user=user,
        featureFlags=FeatureFlags(**services.feature_flags(role=user.role)),
    )


@router.post("/bootstrap", response_model=MeResponse)
def bootstrap_me(
    claims: TokenClaims = Depends(require_valid_token),
    services: AppServices = Depends(get_services),
) -> MeResponse:
    try:
        profile = bootstrap_profile_from_claims(services, claims)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return _me_response(services, user=profile)


@router.get("", response_model=MeResponse)
def get_me(
    auth=Depends(require_user),
    services: AppServices = Depends(get_services),
) -> MeResponse:
    profile = services.storage.get_profile(user_id=auth.user_id)
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found.")
    return _me_response(services, user=profile)
