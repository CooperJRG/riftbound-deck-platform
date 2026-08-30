"""Who a request belongs to, in each mode.

The mode is the whole security model here, so these tests are about what each one
*refuses* as much as what it allows. v2's bug was not that its auth was weak; it was
that a missing environment variable silently turned it off, so the tests that mattered
were the ones nobody wrote.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from riftbound.api.identity import COOKIE_NAME, PUBLIC_PREFIX, sign, unsign
from riftbound.config import ConfigError, load_config
from riftbound.services import reset_services

SECRET = "a-test-secret-that-is-long-enough-to-be-plausible"


@pytest.fixture()
def public_client(client, monkeypatch, tmp_path):
    """The same app the `client` fixture builds, in public mode."""
    monkeypatch.setenv("RB_MODE", "public")
    monkeypatch.setenv("RB_SECRET_KEY", SECRET)
    monkeypatch.setenv("RB_HOST", "127.0.0.1")
    reset_services()
    from riftbound.main import create_app

    with TestClient(create_app()) as public:
        yield public
    reset_services()


def a_deck(name: str) -> dict:
    return {
        "name": name, "format": "constructed", "legendId": "", "championId": "",
        "main": {}, "runes": {}, "battlefields": [], "sideboard": {},
    }


# -- signing -------------------------------------------------------------------


def test_a_signed_value_reads_back():
    assert unsign(sign("v_abc", SECRET), SECRET) == "v_abc"


def test_a_value_signed_with_another_key_does_not():
    assert unsign(sign("v_abc", "another-secret"), SECRET) == ""


@pytest.mark.parametrize(
    "token", ["", "v_abc", "v_abc.", ".mac", "v_abc.deadbeef", "nonsense"]
)
def test_a_cookie_we_did_not_issue_is_refused(token):
    assert unsign(token, SECRET) == ""


def test_the_id_cannot_be_edited_without_breaking_the_signature():
    """Swapping the id for somebody else's has to invalidate the whole token."""
    token = sign("v_mine", SECRET)
    forged = token.replace("v_mine", "v_yours")
    assert unsign(forged, SECRET) == ""


# -- public mode ---------------------------------------------------------------


def test_a_first_visit_is_given_a_shelf(public_client):
    response = public_client.get("/api/cards?limit=1")
    assert response.status_code == 200
    cookie = response.cookies.get(COOKIE_NAME)
    assert cookie
    assert unsign(cookie, SECRET).startswith(PUBLIC_PREFIX)


def test_the_cookie_is_not_readable_by_script(public_client):
    """No script needs it, and an XSS that can read it can move somebody's decks."""
    response = public_client.get("/api/cards?limit=1")
    header = response.headers["set-cookie"].lower()
    assert "httponly" in header
    assert "samesite=lax" in header


def test_two_browsers_get_two_shelves(public_client):
    """The point of a per-browser id over one shared account."""
    public_client.post("/api/decks", json=a_deck("mine"))
    assert [d["name"] for d in public_client.get("/api/decks").json()] == ["mine"]

    stranger = TestClient(public_client.app)
    assert stranger.get("/api/decks").json() == []


def test_a_visitor_keeps_their_decks_across_requests(public_client):
    public_client.post("/api/decks", json=a_deck("first"))
    public_client.post("/api/decks", json=a_deck("second"))
    names = sorted(d["name"] for d in public_client.get("/api/decks").json())
    assert names == ["first", "second"]


def test_a_forged_cookie_gets_a_fresh_shelf_not_somebody_elses(public_client):
    """Refusal has to fail closed into a new identity, never into an existing one."""
    public_client.post("/api/decks", json=a_deck("private"))
    forged = TestClient(public_client.app)
    forged.cookies.set(COOKIE_NAME, f"{PUBLIC_PREFIX}guessed.deadbeef" * 1)
    assert forged.get("/api/decks").json() == []


def test_a_visitor_row_exists_so_a_deck_can_reference_it(public_client):
    """Every table hangs off users(user_id); without the row the first save fails."""
    assert public_client.post("/api/decks", json=a_deck("x")).status_code == 201


# -- the other modes still behave ---------------------------------------------


def test_local_mode_needs_no_cookie(client):
    assert client.get("/api/decks").status_code == 200
    assert COOKIE_NAME not in client.cookies


def test_hosted_mode_still_fails_closed(client, monkeypatch):
    """Unimplemented means 501, not "let everybody in"."""
    monkeypatch.setenv("RB_MODE", "hosted")
    reset_services()
    from riftbound.main import create_app

    with TestClient(create_app()) as hosted:
        assert hosted.get("/api/decks").status_code == 501
    reset_services()


def test_public_mode_refuses_to_start_without_a_secret(monkeypatch):
    """A generated key works until the next restart, then loses everybody's decks."""
    monkeypatch.setenv("RB_MODE", "public")
    monkeypatch.delenv("RB_SECRET_KEY", raising=False)
    with pytest.raises(ConfigError) as caught:
        load_config()
    assert "RB_SECRET_KEY" in str(caught.value)


def test_an_unknown_mode_is_refused(monkeypatch):
    monkeypatch.setenv("RB_MODE", "whatever")
    with pytest.raises(ConfigError):
        load_config()


def test_local_mode_still_refuses_to_bind_the_world(monkeypatch):
    """The guard that makes the implicit single user safe."""
    monkeypatch.setenv("RB_MODE", "local")
    monkeypatch.setenv("RB_HOST", "0.0.0.0")
    with pytest.raises(ConfigError) as caught:
        load_config()
    assert "loopback" in str(caught.value).lower()


def test_health_says_which_mode_is_running(public_client):
    """The one field that tells an operator whether the deployment is what they meant."""
    body = public_client.get("/api/health").json()
    assert body["mode"] == "public"
    assert json.dumps(body)  # stays serialisable
