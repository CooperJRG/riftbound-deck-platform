from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
from uuid import uuid4

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric import rsa
import jwt


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = ROOT.parent
for path in (ROOT, WORKSPACE_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


TEST_SUPABASE_URL = "https://riftbound-beta.test"
TEST_SUPABASE_AUDIENCE = "authenticated"


def create_test_jwks(path: Path) -> tuple[object, dict[str, object]]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
    public_jwk["kid"] = "test-key"
    path.write_text(json.dumps({"keys": [public_jwk]}), encoding="utf-8")
    return private_key, public_jwk


def create_test_ec_jwks(path: Path) -> tuple[object, dict[str, object]]:
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_jwk = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(private_key.public_key()))
    public_jwk["kid"] = "test-ec-key"
    path.write_text(json.dumps({"keys": [public_jwk]}), encoding="utf-8")
    return private_key, public_jwk


def issue_test_token(
    private_key,
    *,
    email: str,
    user_id: str | None = None,
    display_name: str = "Test User",
    role: str = "user",
    audience: str = TEST_SUPABASE_AUDIENCE,
    supabase_url: str = TEST_SUPABASE_URL,
    expires_in_seconds: int = 3600,
    algorithm: str = "RS256",
    key_id: str = "test-key",
) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id or str(uuid4()),
        "aud": audience,
        "iss": f"{supabase_url}/auth/v1",
        "email": email,
        "role": role,
        "exp": int((now + timedelta(seconds=max(60, int(expires_in_seconds)))).timestamp()),
        "iat": int(now.timestamp()),
        "user_metadata": {"display_name": display_name},
        "app_metadata": {"role": role},
    }
    return jwt.encode(payload, private_key, algorithm=algorithm, headers={"kid": key_id})
