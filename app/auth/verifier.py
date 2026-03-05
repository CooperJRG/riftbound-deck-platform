from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import time
from typing import Any
from urllib.parse import urlparse
from urllib.request import urlopen

import jwt


@dataclass(frozen=True)
class TokenClaims:
    user_id: str
    email: str
    raw: dict[str, Any]


class SupabaseJWTVerifier:
    def __init__(self, *, jwks_url: str, audience: str = "authenticated", issuer: str = "", cache_ttl_sec: int = 300):
        self._jwks_url = str(jwks_url or "").strip()
        self._audience = str(audience or "authenticated").strip() or "authenticated"
        self._issuer = str(issuer or "").strip()
        self._cache_ttl_sec = max(30, int(cache_ttl_sec))
        self._cached_jwks: dict[str, Any] | None = None
        self._cached_at = 0.0

    @property
    def configured(self) -> bool:
        return bool(self._jwks_url)

    def _load_raw_jwks(self) -> dict[str, Any]:
        if not self._jwks_url:
            raise RuntimeError("Supabase JWKS URL is not configured.")
        parsed = urlparse(self._jwks_url)
        if parsed.scheme in {"http", "https"}:
            with urlopen(self._jwks_url, timeout=10) as response:
                return json.loads(response.read().decode("utf-8"))
        if parsed.scheme == "file":
            return json.loads(Path(parsed.path).read_text(encoding="utf-8"))
        path = Path(self._jwks_url)
        return json.loads(path.read_text(encoding="utf-8"))

    def _jwks(self) -> dict[str, Any]:
        now = time.time()
        if self._cached_jwks is not None and now - self._cached_at < self._cache_ttl_sec:
            return self._cached_jwks
        payload = self._load_raw_jwks()
        if not isinstance(payload, dict) or not isinstance(payload.get("keys"), list):
            raise RuntimeError("Supabase JWKS payload is invalid.")
        self._cached_jwks = payload
        self._cached_at = now
        return payload

    def _public_key_for_token(self, token: str):
        header = jwt.get_unverified_header(token)
        kid = str(header.get("kid") or "").strip()
        keys = list(self._jwks().get("keys") or [])
        candidates = keys if not kid else [row for row in keys if str(row.get("kid") or "") == kid]
        if not candidates:
            raise RuntimeError("Token signing key was not found in Supabase JWKS.")
        return jwt.PyJWK.from_dict(candidates[0]).key

    def verify(self, token: str) -> TokenClaims:
        clean = str(token or "").strip()
        if not clean:
            raise RuntimeError("Missing bearer token.")
        public_key = self._public_key_for_token(clean)
        options = {"require": ["sub", "aud"]}
        claims = jwt.decode(
            clean,
            key=public_key,
            algorithms=["RS256", "ES256"],
            audience=self._audience,
            issuer=self._issuer or None,
            options=options,
        )
        if not isinstance(claims, dict):
            raise RuntimeError("Supabase token claims are invalid.")
        user_id = str(claims.get("sub") or "").strip()
        email = str(claims.get("email") or "").strip().lower()
        if not user_id or not email:
            raise RuntimeError("Supabase token is missing subject or email.")
        return TokenClaims(user_id=user_id, email=email, raw=claims)
