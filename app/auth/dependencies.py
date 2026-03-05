from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import jwt
from fastapi import Depends, HTTPException, Request, status

from app.auth.verifier import SupabaseJWTVerifier, TokenClaims
from app.core.config import AppConfig
from app.core.services import AppServices, get_services


@dataclass(frozen=True)
class AuthContext:
    user_id: str
    email: str
    role: str
    display_name: str


def _display_name_from_claims(claims: dict[str, Any], email: str) -> str:
    user_meta = claims.get("user_metadata") or {}
    app_meta = claims.get("app_metadata") or {}
    candidates = (
        user_meta.get("display_name"),
        user_meta.get("full_name"),
        claims.get("name"),
        app_meta.get("display_name"),
        email.split("@", 1)[0],
    )
    for value in candidates:
        text = str(value or "").strip()
        if text:
            return text
    return "Riftbound User"


@lru_cache(maxsize=4)
def _build_verifier(jwks_url: str, audience: str, issuer: str) -> SupabaseJWTVerifier:
    return SupabaseJWTVerifier(jwks_url=jwks_url, audience=audience, issuer=issuer)


def get_token_verifier(services: AppServices = Depends(get_services)) -> SupabaseJWTVerifier:
    cfg: AppConfig = services.config
    if not cfg.supabase_jwks_url:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Auth is not configured.")
    issuer = f"{cfg.supabase_url.rstrip('/')}/auth/v1" if cfg.supabase_url else ""
    return _build_verifier(cfg.supabase_jwks_url, cfg.supabase_jwt_audience, issuer)


def _token_from_request(request: Request) -> str:
    raw = str(request.headers.get("Authorization") or "").strip()
    if not raw.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token.")
    token = raw[7:].strip()
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token.")
    return token


def require_valid_token(
    request: Request,
    verifier: SupabaseJWTVerifier = Depends(get_token_verifier),
) -> TokenClaims:
    token = _token_from_request(request)
    try:
        claims = verifier.verify(token)
    except HTTPException:
        raise
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid bearer token.") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    request.state.token_claims = claims
    return claims


def require_user(
    request: Request,
    claims: TokenClaims = Depends(require_valid_token),
    services: AppServices = Depends(get_services),
) -> AuthContext:
    profile = services.storage.get_profile(user_id=claims.user_id)
    if profile is None or str(profile.status or "").strip().lower() != "active":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Beta access is not active for this account.")
    auth = AuthContext(
        user_id=claims.user_id,
        email=profile.email,
        role=profile.role,
        display_name=profile.display_name,
    )
    request.state.auth = auth
    return auth


def require_admin(auth: AuthContext = Depends(require_user)) -> AuthContext:
    if str(auth.role or "").strip().lower() != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access is required.")
    return auth


def bootstrap_profile_from_claims(services: AppServices, claims: TokenClaims):
    display_name = _display_name_from_claims(claims.raw, claims.email)
    return services.storage.bootstrap_user_from_invite(
        user_id=claims.user_id,
        email=claims.email,
        display_name=display_name,
    )
