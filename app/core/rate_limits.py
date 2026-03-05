from __future__ import annotations

import hashlib

from fastapi import Request

try:
    from slowapi import Limiter
except ModuleNotFoundError:  # pragma: no cover - local/dev fallback
    class Limiter:  # type: ignore[override]
        def __init__(self, *args, **kwargs):
            pass

        def limit(self, *_args, **_kwargs):
            def decorator(func):
                return func

            return decorator


def _rate_limit_key(request: Request) -> str:
    auth = getattr(request.state, "auth", None)
    if auth is not None:
        user_id = str(getattr(auth, "user_id", "") or "").strip()
        if user_id:
            return f"user:{user_id}"

    token_claims = getattr(request.state, "token_claims", None)
    if token_claims is not None:
        user_id = str(getattr(token_claims, "user_id", "") or "").strip()
        if user_id:
            return f"claims:{user_id}"

    raw_auth = str(request.headers.get("Authorization") or "").strip()
    if raw_auth:
        digest = hashlib.sha256(raw_auth.encode("utf-8")).hexdigest()
        return f"bearer:{digest}"

    forwarded = str(request.headers.get("X-Forwarded-For") or "").split(",", 1)[0].strip()
    if forwarded:
        return f"ip:{forwarded}"

    client = getattr(request, "client", None)
    host = str(getattr(client, "host", "") or "").strip()
    return f"ip:{host or 'unknown'}"


limiter = Limiter(key_func=_rate_limit_key, headers_enabled=False)
