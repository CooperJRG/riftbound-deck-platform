"""Switching the active card pool must never erase the player's other settings."""
import pytest


@pytest.mark.parametrize("mode", ["open", "exclusion", "collection"])
def test_both_rule_sets_survive_mode_switch_and_reload(client, mode):
    settings = {
        "mode": mode,
        "strict": True,
        "penalty": 0.25,
        "excludedCardIds": ["brazen-buccaneer"],
        "rules": [{"kind": "rarity", "value": "Epic"}],
        "ownedRules": [{"kind": "rarity", "value": "Common"}],
    }
    assert client.put("/api/availability", json=settings).status_code == 200
    for next_mode in ("collection", "open", "exclusion", mode):
        settings["mode"] = next_mode
        assert client.put("/api/availability", json=settings).status_code == 200
        result = client.get("/api/availability").json()
        assert result["mode"] == next_mode
        assert result["strict"] is True
        assert result["penalty"] == 0.25
        assert [r["value"] for r in result["ownedRules"]] == ["Common"]
        assert [r["value"] for r in result["rules"]] == ["Epic"]
        assert [r["cardId"] for r in result["excludedCards"]] == ["brazen-buccaneer"]


def test_excluding_a_card_preserves_collection_shortcuts(client):
    client.put("/api/availability", json={
        "mode": "collection", "ownedRules": [{"kind": "rarity", "value": "Common"}],
    })
    client.post("/api/availability/exclude/brazen-buccaneer")
    result = client.get("/api/availability").json()
    assert result["mode"] == "exclusion"
    assert result["ownedRules"][0]["value"] == "Common"
    # Inactive ownership must not override an explicit exclusion.
    card = client.get("/api/cards", params={"q": "buccaneer"}).json()["cards"][0]
    assert card["reason"] == "excluded:card"
    client.delete("/api/availability/exclude/brazen-buccaneer")
    assert client.get("/api/availability").json()["ownedRules"][0]["value"] == "Common"


@pytest.mark.parametrize("mode", ["open", "exclusion", "collection"])
def test_reset_clears_inactive_owned_rules_and_keeps_saved_decks(client, mode):
    deck = client.post("/api/decks", json={"name": "Keep me", "format": "constructed"}).json()
    client.put("/api/availability", json={
        "mode": mode, "ownedRules": [{"kind": "rarity", "value": "Common"}],
        "excludedCardIds": ["brazen-buccaneer"],
    })
    assert client.delete("/api/availability/collection").status_code == 200
    result = client.get("/api/availability").json()
    assert result["ownedRules"] == []
    assert result["ownedCardCount"] == 0
    assert result["excludedCards"][0]["cardId"] == "brazen-buccaneer"
    assert client.get(f"/api/decks/{deck['deckId']}").status_code == 200


def test_saved_zero_survives_the_session_and_overrides_a_collection_shortcut(meta_client):
    settings = {"mode": "collection", "ownedRules": [{"kind": "rarity", "value": "Common"}]}
    meta_client.put("/api/availability", json=settings)
    session = meta_client.post("/api/smart-decks/sessions", json={"legendId": "vi-piltover-enforcer"}).json()
    proposal = session["proposal"]
    rows = proposal["requirements"]
    missing = next(row for row in rows if row["rarity"] == "Common" and row["zone"] == "main")
    have = {row["cardId"]: row["needed"] for row in rows}
    have[missing["cardId"]] = 0
    path = f"/api/smart-decks/sessions/{session['sessionId']}"
    assert meta_client.post(path + "/answer", json={"deckId": proposal["deck"]["deckId"], "have": have}).status_code == 200
    assert meta_client.post(path + "/save-collection", json={}).status_code == 200
    meta_client.delete(path)
    # A mode switch reloads the recorded count; it must not lose the zero.
    meta_client.put("/api/availability", json={**settings, "mode": "open"})
    meta_client.put("/api/availability", json=settings)
    cards = meta_client.get("/api/cards", params={"q": missing["name"]}).json()["cards"]
    card = next(row for row in cards if row["card"]["cardId"] == missing["cardId"])
    assert card["weight"] < 1
    assert card["reason"] == "not-owned"


def test_saved_counts_are_visible_before_any_mode_was_configured(meta_client):
    session = meta_client.post("/api/smart-decks/sessions", json={"legendId": "vi-piltover-enforcer"}).json()
    proposal = session["proposal"]
    rows = proposal["requirements"]
    counted = next(row for row in rows if row["zone"] == "main" and row["needed"] > 1)
    have = {row["cardId"]: row["needed"] for row in rows}
    have[counted["cardId"]] = 1
    path = f"/api/smart-decks/sessions/{session['sessionId']}"
    meta_client.post(path + "/answer", json={"deckId": proposal["deck"]["deckId"], "have": have})
    meta_client.post(path + "/save-collection", json={})
    assert meta_client.get("/api/availability").json()["ownedCardCount"] >= 1
