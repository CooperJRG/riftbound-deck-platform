"""API tests.

The fixture builds a temporary data root, writes a small bundle, and starts the app.
It takes milliseconds and imports no machine-learning library -- contrast v2, where
this fixture trained an NMF + MoE model and a numerical bug in it failed sixteen
tests covering auth, decks and collections.
"""

from __future__ import annotations

import json
import shutil

import pytest
from fastapi.testclient import TestClient

from riftbound.data.bundle import promote, write_bundle
from riftbound.services import reset_services


@pytest.fixture()
def client(tmp_path, catalog, monkeypatch):
    data_dir = tmp_path / "data"
    (data_dir / "bundles").mkdir(parents=True)
    (data_dir / "rules").mkdir(parents=True)

    written = write_bundle(data_dir / "bundles", list(catalog))
    promote(data_dir / "bundles", written.manifest.bundle_id)

    (data_dir / "rules" / "constructed.json").write_text(
        json.dumps({
            "format": "constructed",
            "description": "test",
            "constraints": {
                "legend_required": True, "legend_card_type": "Legend",
                "chosen_champion_required": True, "champion_super_type": "Champion",
                "main_deck_size_exact": 40, "rune_count_exact": 12,
                "battlefield_count_exact": 3, "battlefield_unique_required": True,
                "main_copy_limit": 3, "combined_main_sideboard_copy_limit": 3,
                "sideboard_max": 8, "domain_identity_enforced": True,
                "rune_card_type": "Rune", "battlefield_card_type": "Battlefield",
                "allowed_main_card_types": ["Unit", "Gear", "Spell"],
                "allowed_sideboard_card_types": ["Unit", "Gear", "Spell"],
                "banned_cards": ["Banned Blade"],
            },
            "rule_refs": {"main_deck_size": ["TR 402.1"]},
        }),
        encoding="utf-8",
    )

    monkeypatch.setenv("RB_MODE", "local")
    monkeypatch.setenv("RB_DATA_DIR", str(data_dir))
    monkeypatch.setenv("RB_DB_PATH", str(data_dir / "test.db"))
    monkeypatch.setattr("riftbound.config.ROOT", tmp_path)
    reset_services()

    from riftbound.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client
    reset_services()


def deck_payload(**overrides):
    main = {"vi-destructive": 3, "brazen-buccaneer": 3, "harpoon-squad": 3,
            "singular-relic": 1, "showcase-only": 3}
    main.update({f"filler-{i:02d}": 3 for i in range(1, 10)})
    payload = {
        "name": "API Deck", "format": "constructed",
        "legendId": "vi-piltover-enforcer", "championId": "vi-destructive",
        "main": main, "runes": {"fury-rune": 12},
        "battlefields": ["the-arena", "the-forge", "the-spire"], "sideboard": {},
    }
    payload.update(overrides)
    return payload


# -- meta ---------------------------------------------------------------------


def test_health_reports_the_bundle_and_migrations(client):
    body = client.get("/api/health").json()
    assert body["ok"] is True
    assert body["mode"] == "local"
    assert body["cardCount"] > 0
    assert "001_initial.sql" in body["migrations"]


def test_formats_expose_constraints_and_resolved_bans(client):
    formats = client.get("/api/formats").json()
    constructed = next(f for f in formats if f["format"] == "constructed")
    # Constraint keys pass through exactly as authored in the rules profile — they are
    # data, not API fields, and they key the profile's rule_refs. Renaming them would
    # break that correspondence.
    assert constructed["constraints"]["main_deck_size_exact"] == 40
    assert constructed["bannedCardIds"] == ["banned-blade"], "ban names resolved to ids"


def test_bundle_endpoint_reports_provenance(client):
    body = client.get("/api/data/bundle").json()
    assert body["bundleId"]
    assert body["cardCount"] > 0


# -- cards --------------------------------------------------------------------


def test_cards_are_listed_with_availability(client):
    body = client.get("/api/cards").json()
    assert body["total"] > 0
    first = body["cards"][0]
    assert first["weight"] == 1.0
    assert "cardId" in first["card"]


def test_card_search_matches_names(client):
    body = client.get("/api/cards", params={"q": "buccaneer"}).json()
    assert [c["card"]["cardId"] for c in body["cards"]] == ["brazen-buccaneer"]


def test_card_filters_combine(client):
    body = client.get("/api/cards", params={"cardType": "Battlefield"}).json()
    assert body["total"] == 3


def test_facets_come_from_the_bundle(client):
    facets = client.get("/api/cards/facets").json()
    assert "Battlefield" in facets["cardTypes"]
    assert "Fury" in facets["domains"]


def test_unknown_card_is_404(client):
    assert client.get("/api/cards/no-such-card").status_code == 404


# -- deck validation ----------------------------------------------------------


def test_a_legal_deck_validates(client):
    body = client.post("/api/decks/validate", json=deck_payload()).json()
    assert body["legal"] is True, body["issues"]
    assert body["mainTotal"] == 40


def test_validation_issues_cite_the_rulebook(client):
    payload = deck_payload()
    payload["main"]["filler-01"] = 1
    body = client.post("/api/decks/validate", json=payload).json()
    issue = next(i for i in body["issues"] if i["code"] == "MAIN_SIZE")
    assert issue["ruleRefs"] == ["TR 402.1"]


def test_unknown_fields_in_a_request_are_rejected(client):
    payload = deck_payload()
    payload["sneaky"] = True
    assert client.post("/api/decks/validate", json=payload).status_code == 422


# -- deck persistence ---------------------------------------------------------


def test_deck_crud_roundtrip(client):
    created = client.post("/api/decks", json=deck_payload())
    assert created.status_code == 201
    deck_id = created.json()["deckId"]

    listed = client.get("/api/decks").json()
    assert [d["deckId"] for d in listed] == [deck_id]
    assert listed[0]["mainTotal"] == 40

    fetched = client.get(f"/api/decks/{deck_id}").json()
    assert fetched["deck"]["legendId"] == "vi-piltover-enforcer"
    assert fetched["deck"]["battlefields"] == ["the-arena", "the-forge", "the-spire"]

    renamed = deck_payload(name="Renamed")
    assert client.put(f"/api/decks/{deck_id}", json=renamed).json()["deck"]["name"] == "Renamed"

    assert client.delete(f"/api/decks/{deck_id}").status_code == 204
    assert client.get(f"/api/decks/{deck_id}").status_code == 404


def test_decks_are_stored_by_card_id_not_by_name(client):
    """The v2 failure this prevents: a renamed card orphaning itself out of a deck."""
    deck_id = client.post("/api/decks", json=deck_payload()).json()["deckId"]
    fetched = client.get(f"/api/decks/{deck_id}").json()
    assert "vi-destructive" in fetched["deck"]["main"]
    assert all("-" in key or key.isalnum() for key in fetched["deck"]["main"])


def test_missing_deck_is_404(client):
    assert client.get("/api/decks/nope").status_code == 404
    assert client.delete("/api/decks/nope").status_code == 404


# -- availability -------------------------------------------------------------


def test_availability_defaults_to_open(client):
    body = client.get("/api/availability").json()
    assert body["mode"] == "open"
    assert "every card" in body["description"]


def test_excluding_one_card_switches_to_exclusion_mode(client):
    """The onboarding path: no collection, one click, immediately useful."""
    body = client.post("/api/availability/exclude/harpoon-squad").json()
    assert body["mode"] == "exclusion"
    assert body["excludedCards"] == [{"cardId": "harpoon-squad", "name": "Harpoon Squad"}]
    assert body["strict"] is False, "soft by default"


def test_excluded_cards_are_de_emphasised_in_card_listings(client):
    client.post("/api/availability/exclude/harpoon-squad")
    body = client.get("/api/cards", params={"q": "harpoon"}).json()
    card = body["cards"][0]
    assert card["weight"] < 1.0
    assert card["available"] is True
    assert card["reason"] == "excluded:card"


def test_excluded_cards_still_allow_a_legal_deck(client):
    """The whole point: exclusion never makes a deck unbuildable."""
    client.post("/api/availability/exclude/harpoon-squad")
    body = client.post("/api/decks/validate", json=deck_payload()).json()
    assert body["legal"] is True
    assert body["coverage"]["penalisedCopies"] == 3
    assert body["coverage"]["complete"] is False


def test_coverage_names_the_cards_the_player_lacks(client):
    client.post("/api/availability/exclude/harpoon-squad")
    coverage = client.post("/api/decks/validate", json=deck_payload()).json()["coverage"]
    assert coverage["missing"] == [
        {
            "cardId": "harpoon-squad",
            "name": "Harpoon Squad",   # named by the server, never a bare id
            "copies": 3,
            "reason": "excluded:card",
        }
    ]


def test_unexcluding_restores_full_weight(client):
    client.post("/api/availability/exclude/harpoon-squad")
    body = client.delete("/api/availability/exclude/harpoon-squad").json()
    assert body["excludedCards"] == []


def test_excluded_cards_come_back_named(client):
    """The client must never have to render a bare card id."""
    client.post("/api/availability/exclude/harpoon-squad")
    entry = client.get("/api/availability").json()["excludedCards"][0]
    assert entry == {"cardId": "harpoon-squad", "name": "Harpoon Squad"}


def test_exclusion_rules_cover_a_class_of_cards(client):
    body = client.put("/api/availability", json={
        "mode": "exclusion", "rules": [{"kind": "rarity", "value": "Epic"}],
    }).json()
    assert body["rules"][0]["description"] == "no Epic cards"
    cards = client.get("/api/cards", params={"q": "harpoon"}).json()["cards"]
    assert cards[0]["weight"] < 1.0


def test_strict_mode_hides_cards_when_asked(client):
    client.put("/api/availability", json={
        "mode": "exclusion", "strict": True, "excludedCardIds": ["harpoon-squad"],
    })
    body = client.get("/api/cards", params={"availableOnly": True, "q": "harpoon"}).json()
    assert body["total"] == 0


def test_availability_survives_a_reload(client):
    client.post("/api/availability/exclude/harpoon-squad")
    stored = client.get("/api/availability").json()["excludedCards"]
    assert [e["cardId"] for e in stored] == ["harpoon-squad"]


def test_excluding_an_unknown_card_is_404(client):
    assert client.post("/api/availability/exclude/not-a-card").status_code == 404


def test_invalid_rule_kind_is_rejected(client):
    response = client.put("/api/availability", json={
        "mode": "exclusion", "rules": [{"kind": "nonsense", "value": "x"}],
    })
    assert response.status_code == 400


def test_rule_kinds_endpoint_lists_values_from_the_bundle(client):
    body = client.get("/api/availability/rule-kinds").json()
    assert "rarity" in body["kinds"]
    assert "Epic" in body["values"]["rarity"]


def test_collection_mode_reports_owned_count(client):
    body = client.put("/api/availability", json={"mode": "collection"}).json()
    assert body["mode"] == "collection"
    assert body["ownedCardCount"] == 0


@pytest.fixture()
def served_client(client, tmp_path):
    """The app with a built UI in place, which is when the SPA fallback exists at all.

    Worth the extra fixture: the fallback is the thing under test, and without a dist
    directory the route is never registered, so a test using the plain client would
    pass while proving nothing.
    """
    dist = tmp_path / "web" / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>app</title>", encoding="utf-8")
    reset_services()

    from riftbound.main import create_app

    with TestClient(create_app()) as served:
        yield served
    reset_services()


def test_an_unknown_api_path_is_json_not_the_app_shell(served_client):
    """The SPA fallback must not answer for /api.

    Serving index.html to a fetch that asked for JSON surfaces as
    `Unexpected token '<', "<!doctype "... is not valid JSON`, which points whoever
    reads it at the parser rather than at the real cause -- usually a running server
    older than the page talking to it.
    """
    response = served_client.get("/api/not-a-real-route")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert "restart the server" in response.json()["detail"]


def test_the_app_shell_still_answers_for_real_pages(served_client):
    """The rule is scoped to /api; deep links into the SPA must keep working."""
    response = served_client.get("/decks/some-deck-id")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")


def test_a_real_api_route_is_untouched_by_the_fallback(served_client):
    response = served_client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["ok"] is True


# -- meta ---------------------------------------------------------------------


@pytest.fixture()
def meta_client(client, catalog, tmp_path):
    """The app with a small promoted meta snapshot."""
    from riftbound.data.meta_snapshot import promote_meta, write_snapshot
    from riftbound.data.meta_normalize import normalize_meta_decks
    from riftbound.domain.meta import Standing, Tournament
    from riftbound.services import get_services
    from tests.test_meta import deck_payload as meta_payload

    services = get_services()
    meta_dir = services.config.meta_dir
    meta_dir.mkdir(parents=True, exist_ok=True)

    tournaments = [Tournament("1", "big", "Big Event", "2026-08-15", "Constructed", 257)]
    payloads = [meta_payload(catalog, slug="winner"), meta_payload(catalog, slug="casual")]
    decks = normalize_meta_decks(
        payloads, catalog=catalog,
        standings=[Standing("big", 1, "Champ", "winner")],
        tournaments=tournaments,
    )
    written = write_snapshot(meta_dir, decks, tournaments, [])
    promote_meta(meta_dir, written.manifest.snapshot_id)
    # Drop the cached (empty) snapshot and everything derived from it, so the app picks
    # the promoted one up. Anything cached off `meta` has to be listed here or it keeps
    # answering from the snapshot that was absent when it was first asked.
    for cached in ("meta", "deck_scores", "legend_index"):
        services.__dict__.pop(cached, None)
    return client


def test_meta_status_reports_absence_rather_than_failing(client):
    """The builder must work with no meta data, so status is always answerable."""
    body = client.get("/api/meta/status").json()
    assert body["available"] is False
    assert body["deckCount"] == 0


def test_meta_endpoints_explain_how_to_populate_them(client):
    response = client.get("/api/meta/decks")
    assert response.status_code == 503
    assert "meta_pipeline build" in response.json()["detail"]


def test_health_reports_meta_absence(client):
    assert client.get("/api/health").json()["metaSnapshotId"] == ""


def test_meta_status_reports_a_promoted_snapshot(meta_client):
    body = meta_client.get("/api/meta/status").json()
    assert body["available"] is True
    assert body["deckCount"] == 2
    assert body["evidenceCounts"]["tournament-placed"] == 1


def test_meta_decks_are_ranked_by_evidence(meta_client):
    decks = meta_client.get("/api/meta/decks").json()
    assert decks[0]["provenance"]["evidence"] == "tournament-placed"
    assert decks[0]["score"]["total"] > decks[-1]["score"]["total"]


def test_a_meta_deck_explains_its_pedigree(meta_client):
    deck = meta_client.get("/api/meta/decks").json()[0]
    assert deck["provenance"]["summary"] == "1st of 257 at Big Event"
    assert deck["provenance"]["url"].startswith("https://riftbound.gg/decks/")


def test_a_meta_deck_exposes_its_score_breakdown(meta_client):
    """A ranking nobody can inspect is a ranking nobody should trust."""
    score = meta_client.get("/api/meta/decks").json()[0]["score"]
    assert set(score) == {"total", "evidence", "placement", "recency", "popularity"}


def test_meta_decks_are_scored_against_what_you_can_field(meta_client):
    """The join that makes meta tracking useful to a casual player."""
    before = meta_client.get("/api/meta/decks").json()[0]
    assert before["coverage"]["complete"] is True

    meta_client.post("/api/availability/exclude/harpoon-squad")
    after = meta_client.get("/api/meta/decks").json()[0]
    assert after["coverage"]["complete"] is False
    assert after["coverage"]["missing"][0]["name"] == "Harpoon Squad"


def test_buildable_only_filters_by_the_availability_profile(meta_client):
    meta_client.post("/api/availability/exclude/harpoon-squad")
    assert meta_client.get("/api/meta/decks", params={"buildableOnly": True}).json() == []


def test_archetypes_group_by_legend_and_champion(meta_client):
    archetypes = meta_client.get("/api/meta/archetypes").json()
    assert len(archetypes) == 1
    assert archetypes[0]["deckCount"] == 2
    assert archetypes[0]["bestPlacement"] == 1
    assert archetypes[0]["bestDeck"]["provenance"]["evidence"] == "tournament-placed"


def test_tournaments_are_listed(meta_client):
    tournaments = meta_client.get("/api/meta/tournaments").json()
    assert tournaments[0]["name"] == "Big Event"
    assert tournaments[0]["players"] == 257


def test_a_meta_deck_can_be_imported_into_the_library(meta_client):
    created = meta_client.post("/api/meta/decks/winner/import")
    assert created.status_code == 201
    body = created.json()
    assert body["name"].endswith("(imported)"), "an imported deck is labelled as one"
    assert body["source"].startswith("https://riftbound.gg/decks/")

    fetched = meta_client.get(f"/api/decks/{body['deckId']}").json()
    assert fetched["deck"]["main"], "the imported list has cards"
    assert fetched["validation"]["mainTotal"] == 40


def test_importing_an_unknown_meta_deck_is_404(meta_client):
    assert meta_client.post("/api/meta/decks/nope/import").status_code == 404


def test_an_invalid_evidence_filter_is_rejected(meta_client):
    response = meta_client.get("/api/meta/decks", params={"evidence": "nonsense"})
    assert response.status_code == 400
