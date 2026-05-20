from __future__ import annotations

import json
from pathlib import Path
import pickle
import time
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
import torch

import app.core.services as services_module
from app.domain.auto_builder_generation import _sigmoid
from app.domain.auto_builder_scoring import ranking_score, resolved_ranking_mode
from app.domain.models import DeckPayload
from app.domain.auto_builder_training import _select_nmf_components, _select_nmf_components_from_metrics, _select_synergy_cluster_count, _select_synergy_cluster_count_from_metrics, train_auto_builder_artifacts
from app.domain.rules import load_format_rules
from app.domain.validator import validate_deck
from app.infra.cards_repo import load_card_catalog
from riftbound.sources.mobalytics import _deck_record_from_html, _sitemap_urls
from riftbound.sources.riftdecks import RiftDecksAdapter
from tests.conftest import TEST_SUPABASE_AUDIENCE, TEST_SUPABASE_URL, create_test_jwks, issue_test_token


def _write_rules_profiles(path: Path) -> tuple[Path, Path]:
    path.mkdir(parents=True, exist_ok=True)
    constructed = {
        "format": "constructed",
        "description": "test constructed",
        "constraints": {
            "legend_required": True,
            "legend_card_type": "Legend",
            "chosen_champion_required": True,
            "champion_super_type": "Champion",
            "main_deck_size_exact": 2,
            "rune_count_exact": 1,
            "battlefield_count_exact": 1,
            "battlefield_unique_required": True,
            "main_copy_limit": 3,
            "combined_main_sideboard_copy_limit": 3,
            "sideboard_max": 2,
            "signature_max_total": 3,
            "domain_identity_enforced": True,
            "rune_card_type": "Rune",
            "battlefield_card_type": "Battlefield",
            "allowed_main_card_types": ["Unit", "Gear", "Spell"],
            "allowed_sideboard_card_types": ["Unit", "Gear", "Spell"],
        },
        "rule_refs": {},
    }
    skirmish = {
        "format": "skirmish",
        "description": "test skirmish",
        "constraints": {
            "legend_required": True,
            "legend_card_type": "Legend",
            "chosen_champion_required": True,
            "champion_super_type": "Champion",
            "main_deck_size_exact": 1,
            "rune_count_exact": 1,
            "battlefield_count_exact": 1,
            "battlefield_unique_required": True,
            "main_copy_limit": 2,
            "combined_main_sideboard_copy_limit": 2,
            "sideboard_max": 1,
            "signature_max_total": 2,
            "domain_identity_enforced": True,
            "rune_card_type": "Rune",
            "battlefield_card_type": "Battlefield",
            "allowed_main_card_types": ["Unit", "Gear", "Spell"],
            "allowed_sideboard_card_types": ["Unit", "Gear", "Spell"],
        },
        "rule_refs": {},
    }
    constructed_path = path / "constructed.json"
    skirmish_path = path / "skirmish.json"
    constructed_path.write_text(json.dumps(constructed), encoding="utf-8")
    skirmish_path.write_text(json.dumps(skirmish), encoding="utf-8")
    return constructed_path, skirmish_path


def _write_cards(path: Path) -> None:
    cards = [
        {
            "title": "Legend A",
            "cardType": "Legend",
            "superType": "",
            "tags": ["A"],
            "color": "Mind",
            "cost": 0,
            "might": 0,
        },
        {
            "title": "Champion A",
            "cardType": "Unit",
            "superType": "Champion",
            "tags": ["A"],
            "color": "Mind",
            "cost": 2,
            "might": 2,
        },
        {
            "title": "Mind Spell",
            "cardType": "Spell",
            "superType": "",
            "tags": [],
            "color": "Mind",
            "cost": 1,
            "might": 0,
        },
        {
            "title": "Mind Gear",
            "cardType": "Gear",
            "superType": "",
            "tags": [],
            "color": "Mind",
            "cost": 1,
            "might": 1,
        },
        {
            "title": "Mind Rune",
            "cardType": "Rune",
            "superType": "",
            "tags": [],
            "color": "Mind",
            "cost": 0,
            "might": 0,
        },
        {
            "title": "Mind Field",
            "cardType": "Battlefield",
            "superType": "",
            "tags": [],
            "color": "Mind",
            "cost": 0,
            "might": 0,
        },
        {
            "title": "Legend B",
            "cardType": "Legend",
            "superType": "",
            "tags": ["B"],
            "color": "Chaos",
            "cost": 0,
            "might": 0,
        },
        {
            "title": "Champion B",
            "cardType": "Unit",
            "superType": "Champion",
            "tags": ["B"],
            "color": "Chaos",
            "cost": 2,
            "might": 2,
        },
        {
            "title": "Chaos Spell",
            "cardType": "Spell",
            "superType": "",
            "tags": [],
            "color": "Chaos",
            "cost": 1,
            "might": 0,
        },
        {
            "title": "Chaos Gear",
            "cardType": "Gear",
            "superType": "",
            "tags": [],
            "color": "Chaos",
            "cost": 1,
            "might": 1,
        },
        {
            "title": "Chaos Rune",
            "cardType": "Rune",
            "superType": "",
            "tags": [],
            "color": "Chaos",
            "cost": 0,
            "might": 0,
        },
        {
            "title": "Chaos Field",
            "cardType": "Battlefield",
            "superType": "",
            "tags": [],
            "color": "Chaos",
            "cost": 0,
            "might": 0,
        },
        {
            "title": "Legend C",
            "cardType": "Legend",
            "superType": "",
            "tags": ["C"],
            "color": "Order",
            "cost": 0,
            "might": 0,
        },
        {
            "title": "Champion C",
            "cardType": "Unit",
            "superType": "Champion",
            "tags": ["C"],
            "color": "Order",
            "cost": 2,
            "might": 2,
        },
        {
            "title": "Order Spell",
            "cardType": "Spell",
            "superType": "",
            "tags": [],
            "color": "Order",
            "cost": 1,
            "might": 0,
        },
        {
            "title": "Order Gear",
            "cardType": "Gear",
            "superType": "",
            "tags": [],
            "color": "Order",
            "cost": 1,
            "might": 1,
        },
        {
            "title": "Order Rune",
            "cardType": "Rune",
            "superType": "",
            "tags": [],
            "color": "Order",
            "cost": 0,
            "might": 0,
        },
        {
            "title": "Order Field",
            "cardType": "Battlefield",
            "superType": "",
            "tags": [],
            "color": "Order",
            "cost": 0,
            "might": 0,
        },
    ]
    path.write_text(json.dumps(cards), encoding="utf-8")


def _write_meta(path: Path, *, include_second: bool = False) -> None:
    rows = [
        {
            "source": "meta",
            "id": "meta-1",
            "name": "Meta Deck One",
            "leaderTitle": "Legend A",
            "cards": {
                "Champion A": 1,
                "Mind Spell": 1,
                "Mind Rune": 1,
                "Mind Field": 1,
            },
        }
    ]
    rows.extend(
        [
            {
                "source": "meta",
                "id": "meta-1b",
                "name": "Meta Deck One Gear",
                "leaderTitle": "Legend A",
                "cards": {
                    "Champion A": 1,
                    "Mind Gear": 1,
                    "Mind Rune": 1,
                    "Mind Field": 1,
                },
            },
            {
                "source": "meta",
                "id": "meta-2",
                "name": "Meta Deck Two",
                "leaderTitle": "Legend B",
                "cards": {
                    "Champion B": 1,
                    "Chaos Spell": 1,
                    "Chaos Rune": 1,
                    "Chaos Field": 1,
                },
            },
            {
                "source": "meta",
                "id": "meta-2b",
                "name": "Meta Deck Two Gear",
                "leaderTitle": "Legend B",
                "cards": {
                    "Champion B": 1,
                    "Chaos Gear": 1,
                    "Chaos Rune": 1,
                    "Chaos Field": 1,
                },
            },
            {
                "source": "meta",
                "id": "meta-3",
                "name": "Meta Deck Three",
                "leaderTitle": "Legend C",
                "cards": {
                    "Champion C": 1,
                    "Order Spell": 1,
                    "Order Rune": 1,
                    "Order Field": 1,
                },
            },
            {
                "source": "meta",
                "id": "meta-3b",
                "name": "Meta Deck Three Gear",
                "leaderTitle": "Legend C",
                "cards": {
                    "Champion C": 1,
                    "Order Gear": 1,
                    "Order Rune": 1,
                    "Order Field": 1,
                },
            },
        ]
    )
    if include_second:
        rows.append(
            {
                "source": "meta",
                "id": "meta-4",
                "name": "Meta Deck Four",
                "leaderTitle": "Legend A",
                "cards": {
                    "Champion A": 1,
                    "Mind Spell": 1,
                    "Mind Rune": 1,
                    "Mind Field": 1,
                },
            }
        )
    path.write_text(json.dumps(rows), encoding="utf-8")


@pytest.fixture()
def app_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    rules_dir = tmp_path / "rules_profiles"
    constructed_path, _skirmish_path = _write_rules_profiles(rules_dir)

    cards_path = tmp_path / "cards.json"
    _write_cards(cards_path)
    meta_path = tmp_path / "meta.json"
    _write_meta(meta_path, include_second=False)
    auto_builder_dir = tmp_path / "auto_builder"
    train_auto_builder_artifacts(
        cards_path=cards_path,
        meta_index_path=meta_path,
        rules_profile_path=constructed_path,
        out_dir=auto_builder_dir,
        epochs=1,
        source_health={
            "riftboundgg": {"fetched": 10, "accepted": 8, "failures": 0, "errors": []},
            "mobalytics": {"fetched": 6, "accepted": 4, "failures": 1, "errors": ["blocked-example"]},
        },
    )
    db_path = tmp_path / "deck-platform.db"
    jwks_path = tmp_path / "supabase-test-jwks.json"
    private_key, _public_jwk = create_test_jwks(jwks_path)
    admin_user_id = str(uuid4())
    admin_email = "admin@example.test"
    admin_token = issue_test_token(
        private_key,
        user_id=admin_user_id,
        email=admin_email,
        display_name="Admin Tester",
        role="admin",
        audience=TEST_SUPABASE_AUDIENCE,
        supabase_url=TEST_SUPABASE_URL,
    )

    monkeypatch.setenv("RB_RULE_PROFILE_PATH", str(constructed_path))
    monkeypatch.setenv("RB_RULES_PROFILES_DIR", str(rules_dir))
    monkeypatch.setenv("RB_CARDS_PATH", str(cards_path))
    monkeypatch.setenv("RB_META_INDEX_PATH", str(meta_path))
    monkeypatch.setenv("RB_AUTO_BUILDER_DIR", str(auto_builder_dir))
    monkeypatch.setenv("RB_AUTO_BUILDER_ENABLED", "1")
    monkeypatch.setenv("RB_DB_PATH", str(db_path))
    monkeypatch.setenv("RB_SUPABASE_URL", TEST_SUPABASE_URL)
    monkeypatch.setenv("RB_SUPABASE_JWKS_URL", str(jwks_path))
    monkeypatch.setenv("RB_SUPABASE_JWT_AUDIENCE", TEST_SUPABASE_AUDIENCE)
    monkeypatch.setenv("RB_ENABLE_MODEL_OBSERVATION", "1")

    services_module._services = None
    from app.main import app

    with TestClient(app) as client:
        services = services_module.get_services()
        services.storage.seed_beta_invite(email=admin_email, role="admin")
        client.headers.update({"Authorization": f"Bearer {admin_token}"})
        bootstrap = client.post("/api/me/bootstrap")
        assert bootstrap.status_code == 200
        yield {
            "client": client,
            "meta_path": meta_path,
            "cards_path": cards_path,
            "rules_path": constructed_path,
            "auto_builder_dir": auto_builder_dir,
            "admin_email": admin_email,
            "admin_user_id": admin_user_id,
            "admin_token": admin_token,
            "private_key": private_key,
        }
    services_module._services = None


def _deck(*, format_name: str, sideboard_qty: int = 0, main_qty: int = 1) -> dict:
    sideboard = {"Mind Spell": sideboard_qty} if sideboard_qty > 0 else {}
    main = {"Champion A": 1}
    if main_qty > 0:
        main["Mind Spell"] = main_qty
    return {
        "name": "Deck A",
        "source": "test",
        "format": format_name,
        "legendTitle": "Legend A",
        "chosenChampionTitle": "Champion A",
        "main": main,
        "runes": {"Mind Rune": 1},
        "battlefields": ["Mind Field"],
        "sideboard": sideboard,
    }


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_bootstrap_rejects_non_invited_user(app_client) -> None:
    client = app_client["client"]
    private_key = app_client["private_key"]
    token = issue_test_token(
        private_key,
        user_id=str(uuid4()),
        email="outsider@example.test",
        display_name="Outsider",
        role="user",
        audience=TEST_SUPABASE_AUDIENCE,
        supabase_url=TEST_SUPABASE_URL,
    )

    response = client.post("/api/me/bootstrap", headers=_auth_headers(token))
    assert response.status_code == 403
    assert "not invited" in response.json()["detail"].lower()


def test_public_private_deck_visibility_is_scoped_by_user(app_client) -> None:
    client = app_client["client"]
    private_key = app_client["private_key"]
    services = services_module.get_services()

    public_row = client.post(
        "/api/decks/library",
        json={
            "name": "Admin Public Deck",
            "source": "test",
            "bucket": "saved",
            "visibility": "public",
            "deck": _deck(format_name="constructed", sideboard_qty=0, main_qty=1),
        },
    )
    assert public_row.status_code == 200
    public_id = public_row.json()["id"]

    private_row = client.post(
        "/api/decks/library",
        json={
            "name": "Admin Private Deck",
            "source": "test",
            "bucket": "saved",
            "visibility": "private",
            "deck": _deck(format_name="constructed", sideboard_qty=0, main_qty=1),
        },
    )
    assert private_row.status_code == 200
    private_id = private_row.json()["id"]

    viewer_email = "viewer@example.test"
    viewer_user_id = str(uuid4())
    services.storage.seed_beta_invite(email=viewer_email, role="user")
    viewer_token = issue_test_token(
        private_key,
        user_id=viewer_user_id,
        email=viewer_email,
        display_name="Viewer",
        role="user",
        audience=TEST_SUPABASE_AUDIENCE,
        supabase_url=TEST_SUPABASE_URL,
    )
    viewer_headers = _auth_headers(viewer_token)

    bootstrap = client.post("/api/me/bootstrap", headers=viewer_headers)
    assert bootstrap.status_code == 200

    library = client.get("/api/decks/library", headers=viewer_headers)
    assert library.status_code == 200
    assert library.json() == []

    public_listing = client.get("/api/decks/public", headers=viewer_headers)
    assert public_listing.status_code == 200
    with services.storage._connect() as conn:
        print("DECKS IN DB:", [dict(r) for r in conn.execute("SELECT id, user_id, name, visibility FROM user_decks").fetchall()])
        print("PROFILES IN DB:", [dict(r) for r in conn.execute("SELECT user_id, email, display_name FROM user_profiles").fetchall()])
    print("PUBLIC LISTING:", public_listing.json())
    listed_ids = {row["id"] for row in public_listing.json()}
    assert public_id in listed_ids
    assert private_id not in listed_ids

    public_detail = client.get(f"/api/decks/public/{public_id}", headers=viewer_headers)
    assert public_detail.status_code == 200
    public_body = public_detail.json()
    assert public_body["visibility"] == "public"
    assert public_body["ownerDisplayName"] == "Admin Tester"
    assert public_body["isOwner"] is False

    private_detail = client.get(f"/api/decks/public/{private_id}", headers=viewer_headers)
    assert private_detail.status_code == 404

    library_detail = client.get(f"/api/decks/library/{public_id}", headers=viewer_headers)
    assert library_detail.status_code == 404


def test_sideboard_validate_and_library_roundtrip(app_client) -> None:
    client = app_client["client"]
    invalid = _deck(format_name="constructed", sideboard_qty=3, main_qty=1)
    validate = client.post("/api/decks/validate", json={"deck": invalid})
    assert validate.status_code == 200
    body = validate.json()
    assert body["is_valid"] is False
    codes = {issue["code"] for issue in body["issues"]}
    assert "COMBINED_COPY_LIMIT" in codes

    valid = _deck(format_name="constructed", sideboard_qty=2, main_qty=1)
    create = client.post(
        "/api/decks/library",
        json={"name": "Sideboard Deck", "source": "test", "bucket": "saved", "deck": valid},
    )
    assert create.status_code == 200
    deck_id = create.json()["id"]

    fetched = client.get(f"/api/decks/library/{deck_id}")
    assert fetched.status_code == 200
    assert fetched.json()["deck"]["sideboard"] == {"Mind Spell": 2}


def test_format_switching_uses_profile_specific_rules(app_client) -> None:
    client = app_client["client"]
    formats = client.get("/api/decks/formats")
    assert formats.status_code == 200
    format_names = {row["format"] for row in formats.json()}
    assert {"constructed", "skirmish"}.issubset(format_names)

    one_card_main = _deck(format_name="constructed", sideboard_qty=0, main_qty=0)
    constructed = client.post("/api/decks/validate", json={"deck": one_card_main})
    assert constructed.status_code == 200
    assert any(issue["code"] == "MAIN_DECK_SIZE" for issue in constructed.json()["issues"])

    one_card_main["format"] = "skirmish"
    skirmish = client.post("/api/decks/validate", json={"deck": one_card_main})
    assert skirmish.status_code == 200
    assert skirmish.json()["is_valid"] is True


def test_meta_refresh_updates_index_and_status(app_client) -> None:
    client = app_client["client"]
    meta_path: Path = app_client["meta_path"]

    initial = client.get("/api/meta/decks?limit=50")
    assert initial.status_code == 200
    initial_count = len(initial.json())
    assert initial_count >= 6
    assert "deck" in initial.json()[0]

    _write_meta(meta_path, include_second=True)
    refreshed = client.post("/api/meta/refresh")
    assert refreshed.status_code == 200
    refresh_body = refreshed.json()
    assert refresh_body["indexedDecks"] == initial_count + 1
    assert refresh_body["lastError"] is None
    assert refresh_body["lastRefreshedAt"]

    status = client.get("/api/meta/status")
    assert status.status_code == 200
    assert status.json()["indexedDecks"] == initial_count + 1

    rows = client.get("/api/meta/decks?limit=50")
    names = {row["deckName"] for row in rows.json()}
    assert "Meta Deck Four" in names


def test_auto_builder_status_recommendations_and_complete(app_client) -> None:
    client = app_client["client"]
    cards = load_card_catalog(app_client["cards_path"])
    rules = load_format_rules(app_client["rules_path"])
    collection_override = {
        "Legend A": 1,
        "Champion A": 1,
        "Mind Spell": 1,
        "Mind Gear": 1,
        "Mind Rune": 1,
        "Mind Field": 1,
        "Legend B": 1,
        "Champion B": 1,
        "Chaos Spell": 1,
        "Chaos Gear": 1,
        "Chaos Rune": 1,
        "Chaos Field": 1,
        "Legend C": 1,
        "Champion C": 1,
        "Order Spell": 1,
        "Order Gear": 1,
        "Order Rune": 1,
        "Order Field": 1,
    }

    status = client.get("/api/auto-builder/status")
    assert status.status_code == 200
    status_body = status.json()
    assert status_body["enabled"] is True
    assert status_body["trainingDeckCount"] >= 4
    assert status_body["winConditionCount"] >= 1
    assert status_body["uniqueShellCount"] >= 3
    assert "runtimeSklearnVersion" in status_body
    assert "trainingMetrics" in status_body
    assert "selectedWinConditionCount" in status_body
    assert "selectedSynergyClusterCount" in status_body
    assert "candidateWinConditionCounts" in status_body
    assert "candidateSynergyClusterCounts" in status_body
    assert "resolutionSelectionMode" in status_body
    assert "resolutionReferenceArtifact" in status_body
    assert "generatorWinVectorSize" in status_body
    assert "generatorClusterVectorSize" in status_body
    assert "embeddingNeighborCount" in status_body
    assert "sourceHealth" in status_body
    assert "mobalytics" in status_body["sourceHealth"]

    recommendations = client.post(
        "/api/auto-builder/recommendations",
        json={
            "rankingMode": "collection",
            "strategyMode": "hybrid",
            "minResults": 3,
            "collectionOverride": collection_override,
        },
    )
    assert recommendations.status_code == 200
    recommendation_body = recommendations.json()
    assert recommendation_body["rankingMode"] == "collection"
    assert recommendation_body["requestedRankingMode"] == "collection"
    assert recommendation_body["returnedResults"] >= 3
    assert recommendation_body["returnedResults"] == len(recommendation_body["recommendations"])
    assert recommendation_body["recommendations"]
    first = recommendation_body["recommendations"][0]
    assert first["winConditionLabel"]
    assert "competitiveScore" in first
    assert first["shellId"]
    assert first["archetypeId"]
    assert "sourceBreakdown" in first
    assert "validationFallback" in first
    assert recommendation_body["buildableMode"] == "mixed"
    assert "strictBuildableResultCount" in recommendation_body
    assert "strictBuildableExhausted" in recommendation_body
    assert [row["rank"] for row in recommendation_body["recommendations"]] == list(range(1, len(recommendation_body["recommendations"]) + 1))
    assert recommendation_body["uniqueShellCount"] == len({row["shellId"] for row in recommendation_body["recommendations"] if row["shellId"]})
    for row in recommendation_body["recommendations"]:
        validation = validate_deck(DeckPayload(**row["deck"]), rules=rules, cards=cards)
        assert validation.is_valid is True

    strict = client.post(
        "/api/auto-builder/recommendations",
        json={
            "rankingMode": "collection",
            "strategyMode": "hybrid",
            "onlyBuildable": True,
            "top": 4,
            "minResults": 4,
            "diversityMode": "none",
            "collectionOverride": {
                "Legend A": 1,
                "Champion A": 1,
                "Mind Spell": 1,
                "Mind Gear": 1,
                "Mind Rune": 1,
                "Mind Field": 1,
            },
        },
    )
    assert strict.status_code == 200
    strict_body = strict.json()
    assert strict_body["rankingMode"] == "competitive"
    assert strict_body["requestedRankingMode"] == "collection"
    assert strict_body["buildableMode"] == "strict"
    assert strict_body["returnedResults"] <= 4
    assert strict_body["strictBuildableResultCount"] == strict_body["returnedResults"]
    strict_scores = [float(row["competitiveScore"] or 0.0) for row in strict_body["recommendations"]]
    assert strict_scores == sorted(strict_scores, reverse=True)
    for row in strict_body["recommendations"]:
        assert row["isBuildable"] is True
        validation = validate_deck(DeckPayload(**row["deck"]), rules=rules, cards=cards)
        assert validation.is_valid is True

    competitive = client.post(
        "/api/auto-builder/recommendations",
        json={
            "rankingMode": "competitive",
            "strategyMode": "hybrid",
            "top": 4,
            "minResults": 4,
            "diversityMode": "none",
            "collectionOverride": collection_override,
        },
    )
    assert competitive.status_code == 200
    competitive_body = competitive.json()
    assert competitive_body["rankingMode"] == "competitive"
    assert competitive_body["requestedRankingMode"] == "competitive"
    competitive_scores = [float(row["competitiveScore"] or 0.0) for row in competitive_body["recommendations"]]
    assert competitive_scores == sorted(competitive_scores, reverse=True)

    hybrid = client.post(
        "/api/auto-builder/recommendations",
        json={
            "rankingMode": "hybrid",
            "strategyMode": "hybrid",
            "top": 4,
            "minResults": 4,
            "diversityMode": "none",
            "collectionOverride": collection_override,
        },
    )
    assert hybrid.status_code == 200
    hybrid_body = hybrid.json()
    assert hybrid_body["rankingMode"] == "hybrid"
    assert hybrid_body["requestedRankingMode"] == "hybrid"

    complete = client.post(
        "/api/auto-builder/complete",
        json={
            "deck": {
                "name": "Partial",
                "source": "builder",
                "format": "constructed",
                "legendTitle": "Legend A",
                "chosenChampionTitle": "Champion A",
                "main": {"Champion A": 1},
                "runes": {"Mind Rune": 1},
                "battlefields": ["Mind Field"],
                "sideboard": {},
            },
            "rankingMode": "collection",
            "strategyMode": "hybrid",
            "collectionOverride": collection_override,
        },
    )
    assert complete.status_code == 200
    complete_body = complete.json()
    assert complete_body["completedCandidates"]
    assert complete_body["bestCandidate"] is not None
    assert complete_body["winConditionLabel"]


def test_auto_builder_status_tolerates_metadata_version_mismatch(app_client) -> None:
    client = app_client["client"]
    metadata_path = app_client["auto_builder_dir"] / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["sklearnVersion"] = "9.9.9"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    services = services_module.get_services()
    services.auto_builder.refresh(force=True)

    status = client.get("/api/auto-builder/status")
    assert status.status_code == 200
    status_body = status.json()
    assert status_body["lastError"] is None
    assert status_body["trainingDeckCount"] >= 4
    assert status_body["runtimeWarnings"]
    assert "artifact 9.9.9" in status_body["runtimeWarnings"][0]


def test_auto_builder_ranking_mode_semantics() -> None:
    assert resolved_ranking_mode("collection", only_buildable=False) == "collection"
    assert resolved_ranking_mode("competitive", only_buildable=False) == "competitive"
    assert resolved_ranking_mode("hybrid", only_buildable=False) == "hybrid"
    assert resolved_ranking_mode("collection", only_buildable=True) == "competitive"

    pure_comp = ranking_score(
        ranking_mode="competitive",
        candidate_score_value=22.0,
        competitive_score=30.0,
        buildable=False,
        completion_pct=25.0,
        replacement_confidence=0.1,
        estimated_completion_cost=500.0,
    )
    hybrid_comp = ranking_score(
        ranking_mode="hybrid",
        candidate_score_value=22.0,
        competitive_score=30.0,
        buildable=False,
        completion_pct=25.0,
        replacement_confidence=0.1,
        estimated_completion_cost=500.0,
    )
    assert pure_comp == 75.0
    assert hybrid_comp > 0.0
    assert hybrid_comp != pure_comp


def test_auto_builder_win_conditions_endpoint_shape(app_client) -> None:
    client = app_client["client"]
    services = services_module.get_services()
    services.auto_builder.refresh(force=True)
    response = client.get("/api/auto-builder/win-conditions")
    assert response.status_code == 200
    body = response.json()
    assert body
    first = body[0]
    assert "id" in first
    assert first["label"]
    assert "sampleDeckCount" in first
    assert "shellCoverageCount" in first
    assert "archetypeCount" in first


def test_auto_builder_sigmoid_handles_large_logits() -> None:
    assert _sigmoid(1_000_000.0) == pytest.approx(1.0)
    assert _sigmoid(-1_000_000.0) == pytest.approx(0.0)


def test_auto_builder_dynamic_component_counts_scale_with_corpus() -> None:
    assert _select_nmf_components(training_deck_count=700, card_vocab_size=80) == 24
    assert _select_nmf_components(training_deck_count=1500, card_vocab_size=80) == 56
    assert _select_nmf_components(training_deck_count=2700, card_vocab_size=80) == 72
    assert _select_synergy_cluster_count(training_deck_count=700, card_vocab_size=80) == 48
    assert _select_synergy_cluster_count(training_deck_count=1500, card_vocab_size=80) == 80
    assert _select_synergy_cluster_count(training_deck_count=2700, card_vocab_size=80) == 80


def test_auto_builder_artifact_persists_selection_metrics(tmp_path: Path) -> None:
    rules_dir = tmp_path / "rules_profiles"
    constructed_path, _ = _write_rules_profiles(rules_dir)
    cards_path = tmp_path / "cards.json"
    _write_cards(cards_path)
    meta_path = tmp_path / "meta.json"
    _write_meta(meta_path, include_second=True)
    out_dir = tmp_path / "auto_builder"
    result = train_auto_builder_artifacts(
        cards_path=cards_path,
        meta_index_path=meta_path,
        rules_profile_path=constructed_path,
        out_dir=out_dir,
        epochs=1,
        source_health={"mobalytics": {"fetched": 2, "accepted": 2, "failures": 0, "errors": []}},
    )
    metadata = result["metadata"]
    assert metadata["selectedWinConditionCount"] >= 1
    assert metadata["selectedSynergyClusterCount"] >= 2
    assert metadata["candidateWinConditionCounts"]
    assert metadata["candidateSynergyClusterCounts"]
    assert metadata["winConditionSelectionMetrics"]
    assert metadata["synergySelectionMetrics"]
    assert metadata["trainingCorpusFingerprint"]
    assert metadata["resolutionSelectionMode"] in {"search", "reuse"}
    assert "sourceHealth" in metadata
    assert metadata["generatorWinVectorSize"] >= 1
    assert metadata["generatorClusterVectorSize"] >= 1
    assert metadata["embeddingNeighborCount"] >= 1

    generator_payload = torch.load(out_dir / "generator_moe.pt", map_location="cpu")
    assert int(generator_payload["winVectorSize"]) >= 1
    assert int(generator_payload["clusterVectorSize"]) >= 1

    with (out_dir / "sklearn_bundle.joblib").open("rb") as fh:
        bundle = pickle.load(fh)
    assert bundle["embeddingNeighbors"]
    assert any(item.get("winConditionVector") for item in bundle["archetypes"])


def test_auto_builder_training_emits_intermediate_progress_updates(tmp_path: Path) -> None:
    rules_dir = tmp_path / "rules_profiles"
    constructed_path, _ = _write_rules_profiles(rules_dir)
    cards_path = tmp_path / "cards.json"
    _write_cards(cards_path)
    meta_path = tmp_path / "meta.json"
    _write_meta(meta_path, include_second=True)
    out_dir = tmp_path / "auto_builder"
    events: list[dict[str, object]] = []

    train_auto_builder_artifacts(
        cards_path=cards_path,
        meta_index_path=meta_path,
        rules_profile_path=constructed_path,
        out_dir=out_dir,
        epochs=3,
        torch_device="cpu",
        progress_callback=lambda payload: events.append(dict(payload)),
    )

    assert any(event.get("stage") == "item2vec" and event.get("stageCurrent") for event in events)
    assert any(event.get("stage") == "win-condition-selection" and event.get("currentCandidate") for event in events)
    assert any(event.get("stage") == "synergy-selection" and event.get("currentCandidate") for event in events)
    assert any(event.get("stage") == "generator-train" and event.get("stageCurrent") for event in events)
    assert any(event.get("stage") == "persist" for event in events)


def test_auto_builder_training_reuses_selected_resolutions_for_matching_corpus(tmp_path: Path) -> None:
    rules_dir = tmp_path / "rules_profiles"
    constructed_path, _ = _write_rules_profiles(rules_dir)
    cards_path = tmp_path / "cards.json"
    _write_cards(cards_path)
    meta_path = tmp_path / "meta.json"
    _write_meta(meta_path, include_second=True)
    baseline_dir = tmp_path / "baseline"
    reused_dir = tmp_path / "reused"

    baseline = train_auto_builder_artifacts(
        cards_path=cards_path,
        meta_index_path=meta_path,
        rules_profile_path=constructed_path,
        out_dir=baseline_dir,
        epochs=1,
        torch_device="cpu",
        resolution_mode="search",
    )
    baseline_meta = baseline["metadata"]

    reused = train_auto_builder_artifacts(
        cards_path=cards_path,
        meta_index_path=meta_path,
        rules_profile_path=constructed_path,
        out_dir=reused_dir,
        epochs=1,
        torch_device="cpu",
        resolution_mode="auto",
        resolution_reference_artifact_dir=baseline_dir,
    )
    reused_meta = reused["metadata"]

    assert reused_meta["resolutionSelectionMode"] == "reuse"
    assert reused_meta["resolutionReferenceArtifact"] == str(baseline_dir)
    assert reused_meta["selectedWinConditionCount"] == baseline_meta["selectedWinConditionCount"]
    assert reused_meta["selectedSynergyClusterCount"] == baseline_meta["selectedSynergyClusterCount"]
    assert reused_meta["candidateWinConditionCounts"] == [baseline_meta["selectedWinConditionCount"]]
    assert reused_meta["candidateSynergyClusterCounts"] == [baseline_meta["selectedSynergyClusterCount"]]


def test_auto_builder_selection_metrics_can_choose_lower_resolution_when_quality_is_better() -> None:
    nmf_choice = _select_nmf_components_from_metrics(
        training_deck_count=1561,
        card_vocab_size=461,
        shell_count=58,
        min_count=56,
        candidate_metrics={
            24: {"compositeScore": 0.6101, "strictBuildableHitRate": 0.6708, "strictBuildableEmptyResultRate": 0.2729, "strictBuildableCandidateDensity": 1.0, "recommendationHitRate": 1.0, "reconstructionRecall": 0.3987},
            56: {"compositeScore": 0.6090, "strictBuildableHitRate": 0.6658, "strictBuildableEmptyResultRate": 0.2729, "strictBuildableCandidateDensity": 1.0, "recommendationHitRate": 1.0, "reconstructionRecall": 0.4706},
            64: {"compositeScore": 0.5955, "strictBuildableHitRate": 0.6691, "strictBuildableEmptyResultRate": 0.2843, "strictBuildableCandidateDensity": 1.0, "recommendationHitRate": 0.9992, "reconstructionRecall": 0.4183},
        },
    )
    assert nmf_choice == 24

    synergy_choice = _select_synergy_cluster_count_from_metrics(
        training_deck_count=1561,
        card_vocab_size=461,
        shell_count=58,
        win_condition_count=64,
        min_count=112,
        candidate_metrics={
            48: {"compositeScore": 0.6014, "replacementQuality": 0.8492, "modularityProxy": 0.3828, "coverageScore": 0.5695},
            64: {"compositeScore": 0.5952, "replacementQuality": 0.8459, "modularityProxy": 0.3877, "coverageScore": 0.5977},
            128: {"compositeScore": 0.4292, "replacementQuality": 0.7781, "modularityProxy": 0.2031, "coverageScore": 0.3760},
        },
    )
    assert synergy_choice == 48


def test_mobalytics_deck_parser_extracts_structured_deck() -> None:
    state = {
        "riftboundState": {
            "apollo": {
                "graphql": {
                    "RiftboundUserGeneratedDocument:test": {
                        "data": {"name": "Fiora, Grand Duelist: Example 1st"},
                        "firstPublishedAt": "2026-02-06T04:39:14Z",
                        "createdAt": "2026-02-06T00:32:15Z",
                        "tags": {"data": [{"groupSlug": "legend", "name": "Fiora, Grand Duelist"}, {"groupSlug": "event", "name": "Regional Open"}]},
                        "content": [
                            {
                                "__typename": "NgfDocumentCmWidgetRichTextV2",
                                "data": {
                                    "title": "Decklist",
                                    "content": {
                                        "root": {
                                            "children": [
                                                {"children": [{"type": "text", "text": "Legend"}]},
                                                {"children": [{"type": "static-data-widget", "label": "Grand Duelist"}]},
                                                {
                                                    "children": [
                                                        {"type": "text", "text": "Runes"},
                                                        {"type": "linebreak"},
                                                        {"type": "text", "text": "1"},
                                                        {"type": "static-data-widget", "label": "Order Rune"},
                                                    ]
                                                },
                                                {"children": [{"type": "text", "text": "Battlefields"}]},
                                                {"children": [{"type": "static-data-widget", "label": "The Dreaming Tree (292)"}]},
                                                {"children": [{"type": "text", "text": "Main Deck"}]},
                                                {
                                                    "children": [
                                                        {"type": "text", "text": "1"},
                                                        {"type": "static-data-widget", "label": "Fiora, Worthy"},
                                                        {"type": "linebreak"},
                                                        {"type": "text", "text": "1"},
                                                        {"type": "static-data-widget", "label": "Honest Broker"},
                                                    ]
                                                },
                                                {"children": [{"type": "text", "text": "Sideboard"}]},
                                                {"children": [{"type": "text", "text": "1"}, {"type": "static-data-widget", "label": "Ignore Me"}]},
                                            ]
                                        }
                                    },
                                },
                            }
                        ],
                    }
                }
            }
        }
    }
    html = f"<script>__PRELOADED_STATE__={json.dumps(state)};</script>"
    record = _deck_record_from_html(url="https://mobalytics.gg/riftbound/decks/example", html=html)
    assert record.source == "mobalytics-tournament"
    assert record.leader_title == "Fiora, Grand Duelist"
    assert record.cards["Order Rune"] == 1
    assert record.cards["The Dreaming Tree"] == 1
    assert record.cards["Fiora, Worthy"] == 1
    assert "Ignore Me" not in record.cards


def test_mobalytics_sitemap_extracts_riftbound_urls() -> None:
    xml_text = """<?xml version="1.0" encoding="UTF-8"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://mobalytics.gg/riftbound/decks/example-deck</loc></url>
      <url><loc>https://mobalytics.gg/riftbound/tournaments/example-event</loc></url>
      <url><loc>https://mobalytics.gg/league-of-legends/builds/example</loc></url>
    </urlset>
    """
    deck_urls, tournament_urls = _sitemap_urls(xml_text)
    assert deck_urls == {"https://mobalytics.gg/riftbound/decks/example-deck"}
    assert tournament_urls == {"https://mobalytics.gg/riftbound/tournaments/example-event"}


def test_riftdecks_manual_dump_adapter_loads_rows(tmp_path: Path) -> None:
    dump_path = tmp_path / "riftdecks.json"
    dump_path.write_text(
        json.dumps(
            [
                {
                    "deckId": "manual-1",
                    "name": "Manual RiftDecks Deck",
                    "source": "riftdecks-manual-import",
                    "url": "https://example.test/deck/manual-1",
                    "cards": {"Champion A": 1, "Mind Spell": 1, "Mind Rune": 1, "Mind Field": 1},
                    "leaderTitle": "Legend A",
                }
            ]
        ),
        encoding="utf-8",
    )
    result = RiftDecksAdapter(manual_dump_path=dump_path).fetch()
    assert result.decks
    assert result.decks[0].deck_id == "manual-1"


def test_meta_and_analysis_include_auto_builder_annotations(app_client) -> None:
    client = app_client["client"]

    meta = client.get("/api/meta/decks?limit=50&sortBy=competitive&sortDir=desc")
    assert meta.status_code == 200
    meta_rows = meta.json()
    assert meta_rows
    assert meta_rows[0]["competitiveScore"] is not None
    assert meta_rows[0]["winConditionLabel"]

    analyze = client.post(
        "/api/decks/analyze",
        json={
            "deck": {
                "name": "Missing Spell",
                "source": "builder",
                "format": "constructed",
                "legendTitle": "Legend A",
                "chosenChampionTitle": "Champion A",
                "main": {"Champion A": 1, "Mind Spell": 1},
                "runes": {"Mind Rune": 1},
                "battlefields": ["Mind Field"],
                "sideboard": {},
            },
            "collectionOverride": {
                "Legend A": 1,
                "Champion A": 1,
                "Mind Rune": 1,
                "Mind Field": 1,
                "Mind Gear": 1,
            },
        },
    )
    assert analyze.status_code == 200
    analysis = analyze.json()["analysis"]
    assert analysis["winConditionLabel"]
    assert analysis["replacement_suggestions"]
    first_option = analysis["replacement_suggestions"][0]["options"][0]
    assert first_option["source"]
    assert "reason" in first_option


def test_model_observation_overview_snapshot_and_training(app_client) -> None:
    client = app_client["client"]

    page = client.get("/model-observation")
    assert page.status_code == 200
    assert "Riftbound Deck Platform v2" in page.text

    overview = client.get("/api/model-observation/overview")
    assert overview.status_code == 200
    overview_body = overview.json()
    assert "status" in overview_body
    assert "training" in overview_body
    assert "models" in overview_body
    assert "observation" in overview_body
    assert "defaults" in overview_body
    assert overview_body["observation"]["winConditions"]
    assert overview_body["defaults"]["minWinConditionCount"] == max(8, overview_body["status"]["selectedWinConditionCount"])
    assert overview_body["defaults"]["minSynergyClusterCount"] == max(16, overview_body["status"]["selectedSynergyClusterCount"])

    snapshot = client.post("/api/model-observation/models/snapshot", json={"label": "Snapshot A"})
    assert snapshot.status_code == 200
    snapshot_body = snapshot.json()
    assert snapshot_body["label"] == "Snapshot A"

    training = client.post(
        "/api/model-observation/training",
        json={
            "label": "Tiny Sweep",
            "epochs": 1,
            "torchDevice": "cpu",
            "syntheticCollection": {
                "packMin": 24,
                "packMax": 32,
                "scenarioCount": 2,
                "runeUnlimited": True,
            },
        },
    )
    assert training.status_code == 200
    training_body = training.json()
    assert training_body["jobId"]
    assert training_body["isRunning"] is True
    assert training_body["events"]
    assert training_body["params"]["minWinConditionCount"] == overview_body["defaults"]["minWinConditionCount"]
    assert training_body["params"]["minSynergyClusterCount"] == overview_body["defaults"]["minSynergyClusterCount"]

    final_status = training_body
    for _idx in range(120):
        time.sleep(0.05)
        final_status = client.get("/api/model-observation/training").json()
        if not final_status["isRunning"]:
            break
    assert final_status["status"] in {"completed", "failed"}
    assert final_status["status"] == "completed"

    models = client.get("/api/model-observation/models")
    assert models.status_code == 200
    model_rows = models.json()
    assert any(row["label"] == "Tiny Sweep" for row in model_rows)

    trained_row = next(row for row in model_rows if row["label"] == "Tiny Sweep")
    promote = client.post(f"/api/model-observation/models/{trained_row['id']}/promote")
    assert promote.status_code == 200
    assert promote.json()["isProduction"] is True


def test_model_observation_shell_is_public_but_data_requires_auth(app_client) -> None:
    client = app_client["client"]
    auth_header = client.headers.pop("Authorization", None)
    try:
        page = client.get("/model-observation")
        assert page.status_code == 200
        assert "Riftbound Deck Platform v2" in page.text

        overview = client.get("/api/model-observation/overview")
        assert overview.status_code == 401
    finally:
        if auth_header is not None:
            client.headers["Authorization"] = auth_header


def test_collection_export_import_and_reset_guardrails(app_client) -> None:
    client = app_client["client"]
    put_one = client.put("/api/collection/item", json={"card": "Mind Spell", "quantity": 3})
    assert put_one.status_code == 200

    export_json = client.get("/api/collection/export?format=json")
    assert export_json.status_code == 200
    payload = export_json.json()
    assert payload["cards"]["Mind Spell"] == 3

    export_csv = client.get("/api/collection/export?format=csv")
    assert export_csv.status_code == 200
    assert "card_name,total_quantity" in export_csv.text
    assert "Mind Spell,3" in export_csv.text

    replace_payload = {"cards": {"Mind Spell": 1, "Champion A": 2}}
    imported = client.post(
        "/api/collection/import-json",
        json={"jsonText": json.dumps(replace_payload), "replaceExisting": True},
    )
    assert imported.status_code == 200
    assert imported.json()["cards"] == {"Champion A": 2, "Mind Spell": 1}

    blocked = client.post("/api/collection/reset", json={"confirmPhrase": "NOPE", "createBackup": True})
    assert blocked.status_code == 400

    reset = client.post("/api/collection/reset", json={"confirmPhrase": "RESET", "createBackup": True})
    assert reset.status_code == 200
    reset_body = reset.json()
    assert reset_body["reset"] is True
    assert reset_body["backup"]["total_copies"] == 3
    assert reset_body["snapshot"]["total_copies"] == 0


def test_deck_analyze_includes_completion_cost_and_tcgplayer_links(app_client) -> None:
    client = app_client["client"]
    deck = {
        "name": "Analyze Deck",
        "source": "test",
        "format": "constructed",
        "legendTitle": "Legend A",
        "chosenChampionTitle": "Champion A",
        "main": {"Champion A": 1, "Mind Spell": 1},
        "runes": {"Mind Rune": 1},
        "battlefields": ["Mind Field"],
        "sideboard": {},
    }
    analyze = client.post("/api/decks/analyze", json={"deck": deck})
    assert analyze.status_code == 200
    body = analyze.json()
    analysis = body["analysis"]
    assert "estimated_completion_cost" in analysis
    assert "missing_cards_priced" in analysis
    assert "missing_cards_unpriced" in analysis

    missing_rows = analysis["missing_cards"]
    assert missing_rows
    first = missing_rows[0]
    assert "tcgplayer_url" in first
    assert "tcgplayer.com/search/all/product" in first["tcgplayer_url"]
