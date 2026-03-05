from __future__ import annotations

from app.auth.verifier import SupabaseJWTVerifier
from tests.conftest import TEST_SUPABASE_AUDIENCE, TEST_SUPABASE_URL, create_test_ec_jwks, issue_test_token


def test_verifier_accepts_es256_supabase_tokens(tmp_path) -> None:
    jwks_path = tmp_path / "supabase-ec-jwks.json"
    private_key, _public_jwk = create_test_ec_jwks(jwks_path)
    token = issue_test_token(
        private_key,
        email="ec-user@example.test",
        display_name="EC User",
        role="user",
        audience=TEST_SUPABASE_AUDIENCE,
        supabase_url=TEST_SUPABASE_URL,
        algorithm="ES256",
        key_id="test-ec-key",
    )
    verifier = SupabaseJWTVerifier(
        jwks_url=str(jwks_path),
        audience=TEST_SUPABASE_AUDIENCE,
        issuer=f"{TEST_SUPABASE_URL}/auth/v1",
    )

    claims = verifier.verify(token)

    assert claims.email == "ec-user@example.test"
    assert claims.user_id
