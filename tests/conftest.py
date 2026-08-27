"""Test fixtures.

Deliberately tiny and pure. In v2 the API test fixture called
``train_auto_builder_artifacts(...)`` -- it trained an NMF + MoE model before every
test -- so one numerical bug in the ML pipeline took down sixteen unrelated tests
covering auth, deck visibility and collection import. Nothing here loads a bundle,
touches the network, or imports a machine-learning library.
"""

from __future__ import annotations

import sys
from itertools import count
from pathlib import Path

import pytest

SERVER = Path(__file__).resolve().parents[1] / "server"
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))

from riftbound.domain.cards import Card, Printing, build_catalog  # noqa: E402
from riftbound.domain.rules import FormatRules  # noqa: E402

# Collector codes must be unique: decklists reference cards by code, so a fixture that
# reuses a number silently collapses the catalogue. A counter rather than a hash of the
# id, because Python randomises string hashing per process — that would make the whole
# meta suite intermittently fail.
_card_numbers = count(1)


def make_card(
    card_id: str,
    name: str = "",
    *,
    card_type: str = "Unit",
    super_type: str = "",
    domains: tuple[str, ...] = ("Fury",),
    domains_ok: bool = True,
    cost: int | None = 2,
    might: int | None = 2,
    tags: tuple[str, ...] = (),
    champion_tags: tuple[str, ...] = (),
    unique: bool = False,
    rarity: str = "Common",
    set_code: str = "OGN",
    number: str = "",
    promo: bool = False,
) -> Card:
    card_number = number or f"{next(_card_numbers):04d}"
    return Card(
        card_id=card_id,
        name=name or card_id.replace("-", " ").title(),
        card_type=card_type,
        super_type=super_type,
        domains=domains,
        domains_ok=domains_ok,
        cost=cost,
        might=might,
        tags=tags,
        champion_tags=champion_tags,
        effect="",
        flavor="",
        unique=unique,
        printings=(
            Printing(
                print_id=f"{set_code.lower()}-{card_number}-{card_id}",
                card_id=card_id,
                title=name or card_id,
                set_code=set_code,
                set_name=set_code,
                card_number=card_number,
                rarity=rarity,
                promo=promo,
                image_url="",
            ),
        ),
    )


@pytest.fixture()
def catalog():
    """A minimal but realistic catalogue: one legend, its champion, filler, runes."""
    cards = [
        make_card(
            "vi-piltover-enforcer", "Vi - Piltover Enforcer",
            card_type="Legend", domains=("Fury",), cost=None, might=None,
            tags=("Vi", "Piltover"), champion_tags=("Vi",),
        ),
        make_card(
            "vi-destructive", "Vi - Destructive",
            super_type="Champion", domains=("Fury",),
            tags=("Vi", "Piltover"), champion_tags=("Vi",), rarity="Rare",
        ),
        make_card("brazen-buccaneer", "Brazen Buccaneer", domains=("Fury",)),
        make_card("harpoon-squad", "Harpoon Squad", domains=("Fury",), rarity="Epic"),
        make_card("calm-intruder", "Calm Intruder", domains=("Calm",)),
        make_card(
            "singular-relic", "Singular Relic",
            card_type="Gear", domains=("Fury",), unique=True,
        ),
        make_card(
            "fury-rune", "Fury Rune",
            card_type="Rune", super_type="Basic", domains=("Fury",), cost=None, might=None,
        ),
        make_card(
            "calm-rune", "Calm Rune",
            card_type="Rune", super_type="Basic", domains=("Calm",), cost=None, might=None,
        ),
        make_card(
            "the-arena", "The Arena",
            card_type="Battlefield", domains=("Fury",), cost=None, might=None,
        ),
        make_card(
            "the-forge", "The Forge",
            card_type="Battlefield", domains=("Fury",), cost=None, might=None,
        ),
        make_card(
            "the-spire", "The Spire",
            card_type="Battlefield", domains=("Fury",), cost=None, might=None,
        ),
        make_card(
            "showcase-only", "Showcase Only",
            domains=("Fury",), rarity="Showcase", promo=True, set_code="UNL",
        ),
        make_card("banned-blade", "Banned Blade", domains=("Fury",)),
    ]
    # Filler so a test deck can reach a legal 40 cards without noise. 01-09 fill the
    # main deck; 10-14 are deliberately left out of it so sideboard tests have cards
    # that do not collide with the combined main+sideboard copy limit.
    cards += [
        make_card(f"filler-{i:02d}", f"Filler {i:02d}", domains=("Fury",))
        for i in range(1, 15)
    ]
    return build_catalog(cards)


@pytest.fixture()
def rules():
    return FormatRules(
        format_name="constructed",
        description="test profile",
        constraints={
            "legend_required": True,
            "legend_card_type": "Legend",
            "chosen_champion_required": True,
            "champion_super_type": "Champion",
            "main_deck_size_exact": 40,
            "rune_count_exact": 12,
            "battlefield_count_exact": 3,
            "battlefield_unique_required": True,
            "main_copy_limit": 3,
            "combined_main_sideboard_copy_limit": 3,
            "sideboard_max": 8,
            "signature_max_total": 3,
            "domain_identity_enforced": True,
            "rune_card_type": "Rune",
            "battlefield_card_type": "Battlefield",
            "allowed_main_card_types": ["Unit", "Gear", "Spell"],
            "allowed_sideboard_card_types": ["Unit", "Gear", "Spell"],
            "banned_cards": ["Banned Blade"],
        },
        rule_refs={
            "main_deck_size": ["TR 402.1", "TR 601.1.b"],
            "main_copy_limit": ["CR 103.2.b"],
            "legend_required": ["CR 103.1"],
        },
    )


@pytest.fixture()
def bound_rules(rules, catalog):
    return rules.bind(catalog)


@pytest.fixture()
def legal_deck(catalog):
    """A deck that passes every check, for tests to perturb."""
    from riftbound.domain.deck import Deck

    main = {
        "vi-destructive": 3,
        "brazen-buccaneer": 3,
        "harpoon-squad": 3,
        "singular-relic": 1,
        "showcase-only": 3,
    }
    main.update({f"filler-{i:02d}": 3 for i in range(1, 10)})  # 13 + 27 = 40
    return Deck.make(
        name="Test Deck",
        legend_id="vi-piltover-enforcer",
        champion_id="vi-destructive",
        main=main,
        runes={"fury-rune": 12},
        battlefields=["the-arena", "the-forge", "the-spire"],
    )


# -- the application ----------------------------------------------------------
#
# These live here rather than in one test module because three suites need them, and a
# fixture imported across test files reads to every linter (correctly) as a redefinition
# -- pytest's own home for a shared fixture is conftest.

import json  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from riftbound.data.bundle import promote, write_bundle  # noqa: E402
from riftbound.services import reset_services  # noqa: E402


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
            # A two-era profile, because the API contract for a win rate includes
            # saying which format it describes. A profile with no eras is exercised
            # separately in test_meta_performance -- it must degrade to "unknown"
            # rather than fail to load a format.
            "eras": {
                "periods": [
                    {
                        "id": "launch", "name": "Launch", "to": "2026-03-28",
                        "bans_introduced": [], "evidence": "test fixture", "source": "",
                    },
                    {
                        "id": "post-ban", "name": "Post ban", "from": "2026-03-29",
                        "bans_introduced": ["Banned Blade"],
                        "evidence": "test fixture", "source": "",
                    },
                ]
            },
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



@pytest.fixture()
def meta_client(client, catalog, tmp_path):
    """The app with a small promoted meta snapshot."""
    from tests.test_meta import deck_payload as meta_payload

    from riftbound.data.meta_normalize import normalize_meta_decks
    from riftbound.data.meta_snapshot import promote_meta, write_snapshot
    from riftbound.domain.meta import Standing, Tournament
    from riftbound.services import get_services

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



@pytest.fixture()
def meta_records_client(client, catalog, tmp_path):
    """The app with a snapshot whose standings carry match records.

    Separate from ``meta_client`` because the two prove different things: that one has
    no records at all, which is exactly the "not measured" case the win-rate column has
    to render honestly, and losing that coverage by folding the fixtures together would
    be easy to do by accident.

    Deliberately spread over enough events and matches to clear the publishing
    thresholds for one archetype and fall short for another, so both branches are
    exercised end to end.
    """
    from tests.test_meta import deck_payload as meta_payload

    from riftbound.data.meta_normalize import normalize_meta_decks
    from riftbound.data.meta_snapshot import promote_meta, write_snapshot
    from riftbound.domain.meta import Standing, Tournament
    from riftbound.services import get_services

    services = get_services()
    meta_dir = services.config.meta_dir
    meta_dir.mkdir(parents=True, exist_ok=True)

    tournaments, payloads, standings = [], [], []
    for event in range(10):
        slug = f"ev-{event}"
        tournaments.append(
            Tournament(slug, slug, f"Event {event}", "2026-08-15", "Constructed", 64, decks_published=64)
        )
        for seat in range(12):
            deck_slug = f"{slug}::{seat}"
            payloads.append(meta_payload(catalog, slug=deck_slug))
            standings.append(
                Standing(
                    tournament_slug=slug, place=seat + 1, player_name=f"player-{event}-{seat}",
                    deck_slug=deck_slug, record="3-1", wins=3, losses=1, draws=0,
                )
            )
    decks = normalize_meta_decks(
        payloads, catalog=catalog, standings=standings, tournaments=tournaments
    )
    written = write_snapshot(meta_dir, decks, tournaments, standings)
    promote_meta(meta_dir, written.manifest.snapshot_id)
    for cached in ("meta", "deck_scores", "legend_index"):
        services.__dict__.pop(cached, None)
    return client



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


def test_refresh_status_answers_even_with_no_meta(client):
    """A stale snapshot looks exactly like a fresh one from outside, so this must
    always be answerable -- including when there is nothing to be fresh about."""
    body = client.get("/api/meta/refresh").json()
    assert body["snapshotAgeHours"] == -1.0
    assert body["stale"] is False, "nothing cannot be stale"
    assert body["lastRun"] is None


def test_refresh_status_reports_the_schedule(client):
    body = client.get("/api/meta/refresh").json()
    assert body["enabled"] is True, "local mode keeps its own data current"
    assert body["intervalHours"] > 0
    assert body["status"] in {"idle", "running", "off"}


def test_a_refresh_can_be_triggered_without_a_terminal(client, monkeypatch):
    """The honest answer to "run the meta pipeline" for somebody on a web page."""
    from riftbound.data.scheduler import RunRecord

    record = RunRecord(
        started_at="2026-08-26T00:00:00+00:00", finished_at="2026-08-26T00:01:00+00:00",
        ok=True, promoted=True, snapshot_id="snap-test", deck_count=1234,
        duration_ms=1000, message="",
    )
    monkeypatch.setattr(
        "riftbound.data.scheduler.run_refresh", lambda config, budget: record
    )
    response = client.post("/api/meta/refresh")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["lastRun"]["snapshotId"] == "snap-test"
    assert body["lastRun"]["deckCount"] == 1234
    assert body["runs"] == 1


def test_a_failed_refresh_is_reported_not_raised(client, monkeypatch):
    """Meta is optional data; a bad harvest degrades the meta view and nothing else."""
    def explode(config, budget):
        raise RuntimeError("upstream unreachable")

    monkeypatch.setattr("riftbound.data.scheduler.run_refresh", explode)
    response = client.post("/api/meta/refresh")
    assert response.status_code == 200
    body = response.json()
    assert body["lastRun"]["ok"] is False
    assert "upstream unreachable" in body["lastRun"]["message"]
    assert body["consecutiveFailures"] == 1


