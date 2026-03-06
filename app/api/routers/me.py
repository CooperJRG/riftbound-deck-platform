from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.auth.dependencies import bootstrap_profile_from_claims, require_user, require_valid_token
from app.auth.verifier import TokenClaims
from app.core.rate_limits import limiter
from app.core.services import AppServices, get_services
from app.domain.models import FeatureFlags, MeResponse, UpdateDisplayNameRequest

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


@router.put("/display-name", response_model=MeResponse)
@limiter.limit("10/minute")
def update_display_name(
    request: Request,
    body: UpdateDisplayNameRequest,
    auth=Depends(require_user),
    services: AppServices = Depends(get_services),
) -> MeResponse:
    clean = str(body.display_name or "").strip()[:32]
    if not clean:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Display name cannot be empty.")
    try:
        profile = services.storage.update_display_name(user_id=auth.user_id, display_name=clean)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _me_response(services, user=profile)
