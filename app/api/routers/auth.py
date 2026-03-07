from __future__ import annotations

import json
import urllib.error
import urllib.request

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.core.rate_limits import limiter
from app.core.services import AppServices, get_services

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _supabase_admin_headers(service_role_key: str) -> dict[str, str]:
    return {
        "apikey": service_role_key,
        "Authorization": f"Bearer {service_role_key}",
        "Content-Type": "application/json",
    }


def _find_supabase_user(supabase_url: str, service_role_key: str, email: str) -> dict | None:
    """Return the Supabase user record for the given email, or None."""
    # GoTrue admin API uses `filter` for text search; do exact client-side match to avoid
    # returning the wrong user when `email=` query param is ignored by older GoTrue versions.
    email_lower = email.strip().lower()
    url = f"{supabase_url.rstrip('/')}/auth/v1/admin/users?page=1&per_page=50&filter={urllib.request.quote(email_lower, safe='')}"
    req = urllib.request.Request(url, headers=_supabase_admin_headers(service_role_key))
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            users = data.get("users") or []
            for user in users:
                if str(user.get("email") or "").strip().lower() == email_lower:
                    return user
            return None
    except Exception:
        return None


def _create_supabase_user(supabase_url: str, service_role_key: str, email: str, password: str) -> str:
    """Create a new confirmed Supabase user. Returns the user_id."""
    url = f"{supabase_url.rstrip('/')}/auth/v1/admin/users"
    payload = json.dumps({"email": email, "password": password, "email_confirm": True}).encode()
    req = urllib.request.Request(url, data=payload, headers=_supabase_admin_headers(service_role_key), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            return str(data.get("id", ""))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Could not create account: {body}") from exc


def _set_supabase_password(supabase_url: str, service_role_key: str, user_id: str, password: str) -> None:
    """Update an existing Supabase user's password and confirm their email."""
    url = f"{supabase_url.rstrip('/')}/auth/v1/admin/users/{user_id}"
    payload = json.dumps({"password": password, "email_confirm": True}).encode()
    req = urllib.request.Request(url, data=payload, headers=_supabase_admin_headers(service_role_key), method="PUT")
    try:
        with urllib.request.urlopen(req, timeout=15) as _resp:
            pass
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Could not set password: {body}") from exc


@router.post("/setup")
@limiter.limit("5/hour")
async def account_setup(
    request: Request,
    services: AppServices = Depends(get_services),
) -> dict:
    try:
        raw = await request.json()
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON body.")
    email = str(raw.get("email") or "").strip().lower()
    password = str(raw.get("password") or "").strip()

    if not email or not password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email and password are required.")
    if len(password) < 8:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Password must be at least 8 characters.")

    if not services.config.supabase_url or not services.config.supabase_service_role_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Account setup is not available in this environment.",
        )

    # Check the email is on the beta invite list.
    invite = services.storage.get_beta_invite(email=email)
    if invite is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This email is not on the beta invite list.")
    if invite.status == "revoked":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This beta invite has been revoked.")

    supabase_url = services.config.supabase_url
    service_role_key = services.config.supabase_service_role_key

    try:
        existing = _find_supabase_user(supabase_url, service_role_key, email)
        if existing:
            _set_supabase_password(supabase_url, service_role_key, str(existing["id"]), password)
        else:
            _create_supabase_user(supabase_url, service_role_key, email, password)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return {"ok": True, "message": "Account set up. You can now sign in."}
