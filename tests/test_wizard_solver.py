from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.domain.models import DeckPayload
from app.domain.normalization import normalize_card_key
from app.domain.rules import load_format_rules
from app.domain.validator import validate_deck
from app.domain.wizard_solver import apply_wizard_main_swap, solve_wizard_deck
from app.infra.cards_repo import CardCatalog, CardRecord


def _card(
    title: str,
    card_type: str,
    super_type: str = "",
    champion_tags: tuple[str, ...] = (),
    domains: tuple[str, ...] = ("Mind",),
    is_unique: bool = False,
) -> CardRecord:
    return CardRecord(
        title=title,
        card_type=card_type,
        super_type=super_type,
        tags=champion_tags,
        champion_tags=champion_tags,
        domains=domains,
        domain_parse_ok=True,
        cost=2,
        might=2,
        image_url="",
        is_unique=is_unique,
    )


def _catalog() -> CardCatalog:
    cards = [
        _card("LeBlanc - Deceiver", "Legend", champion_tags=("LeBlanc",)),
        _card("LeBlanc - Fragmented", "Unit", super_type="Champion", champion_tags=("LeBlanc",)),
        _card("Mind Rune", "Rune"),
        _card("Hall of Legends", "Battlefield"),
        _card("Forgotten Monument", "Battlefield"),
        _card("Skyline Rift", "Battlefield"),
        _card("Karthus - Eternal", "Unit"),
        _card("Deathgrip", "Spell"),
        _card("Mirror Image", "Spell"),
        _card("Sacrifice", "Spell"),
        _card("Tactical Retreat", "Spell"),
        _card("Deceiver's Gambit", "Spell"),
        _card("Black Rose Agent", "Unit"),
        _card("Sigil Snare", "Spell"),
        _card("Guile", "Spell"),
        _card("Shadow Step", "Spell"),
        _card("Distortion", "Spell"),
        _card("Chain Lash", "Gear"),
        _card("Whispered Plan", "Spell"),
        _card("Mimic", "Spell"),
        _card("Veiled Blade", "Gear"),
    ]
    return CardCatalog(
        cards=tuple(cards),
        by_title={card.title: card for card in cards},
        by_key={normalize_card_key(card.title): card for card in cards},
    )


def _rules():
    profile_path = Path(__file__).resolve().parents[1] / "rules_profiles" / "constructed.json"
    return load_format_rules(profile_path)


def _reference_deck() -> DeckPayload:
    main = {
        "LeBlanc - Fragmented": 1,
        "Karthus - Eternal": 3,
        "Mirror Image": 3,
        "Sacrifice": 3,
        "Tactical Retreat": 3,
        "Deceiver's Gambit": 3,
        "Black Rose Agent": 3,
        "Sigil Snare": 3,
        "Guile": 3,
        "Shadow Step": 3,
        "Distortion": 3,
        "Chain Lash": 3,
        "Whispered Plan": 3,
        "Mimic": 3,
    }
    return DeckPayload(
        name="LeBlanc Reference",
        source="test",
        format="constructed",
        legendTitle="LeBlanc - Deceiver",
        chosenChampionTitle="LeBlanc - Fragmented",
        main=main,
        runes={"Mind Rune": 12},
        battlefields=["Hall of Legends", "Forgotten Monument", "Skyline Rift"],
        sideboard={},
    )


def _lillia_catalog() -> CardCatalog:
    calm = ("Calm",)
    mind = ("Mind",)
    both = ("Calm", "Mind")
    cards = [
        _card("Lillia - Bashful Bloom", "Legend", champion_tags=("Lillia",), domains=both),
        _card("Lillia - Fae Fawn", "Unit", super_type="Champion", champion_tags=("Lillia",), domains=mind),
        _card("Calm Rune", "Rune", domains=calm),
        _card("Mind Rune", "Rune", domains=mind),
        _card("Black Flame Altar", "Battlefield", domains=both),
        _card("Dusk Rose Lab", "Battlefield", domains=both),
        _card("Forbidding Waste", "Battlefield", domains=both),
        _card("Charm", "Spell", domains=calm),
        _card("Defy", "Spell", domains=calm),
        _card("Discipline", "Spell", domains=calm),
        _card("Stupefy", "Spell", domains=mind),
        _card("Ravenbloom Student", "Unit", domains=mind),
        _card("Thousand-Tailed Watcher", "Unit", domains=mind),
        _card("Disarming Rake", "Unit", domains=calm),
        _card("Heart of Dark Ice", "Gear", domains=calm),
        _card("Plundering Poro", "Unit", domains=mind),
        _card("Back Off", "Spell", domains=calm),
        _card("Sprite Burst", "Spell", domains=mind),
        _card("Turn to Dust", "Spell", domains=mind),
        _card("Sprite Fountain", "Gear", domains=mind),
        _card("Smoke and Mirrors", "Spell", domains=mind),
        _card("Sprite Queen", "Unit", domains=mind),
        _card("Lilting Lullaby", "Spell", super_type="Signature", champion_tags=("Lillia",), domains=both),
        _card("Dream-Laden Bough", "Gear", domains=mind),
        _card("Sleepy Sprout", "Unit", domains=mind),
        _card("Gentle Bloom", "Spell", domains=calm),
    ]
    return CardCatalog(
        cards=tuple(cards),
        by_title={card.title: card for card in cards},
        by_key={normalize_card_key(card.title): card for card in cards},
    )


def _lillia_reference_deck() -> DeckPayload:
    main = {
        "Lillia - Fae Fawn": 1,
        "Charm": 3,
        "Defy": 3,
        "Discipline": 3,
        "Stupefy": 3,
        "Ravenbloom Student": 3,
        "Thousand-Tailed Watcher": 2,
        "Disarming Rake": 1,
        "Heart of Dark Ice": 3,
        "Plundering Poro": 3,
        "Back Off": 1,
        "Sprite Burst": 3,
        "Turn to Dust": 2,
        "Sprite Fountain": 3,
        "Smoke and Mirrors": 3,
        "Sprite Queen": 2,
        "Lilting Lullaby": 1,
    }
    return DeckPayload(
        name="Lillia Reference",
        source="test",
        format="constructed",
        legendTitle="Lillia - Bashful Bloom",
        chosenChampionTitle="Lillia - Fae Fawn",
        main=main,
        runes={"Calm Rune": 6, "Mind Rune": 6},
        battlefields=["Black Flame Altar", "Dusk Rose Lab", "Forbidding Waste"],
        sideboard={},
    )


def test_owned_solver_never_outputs_four_deathgrip_unless_legal() -> None:
    catalog = _catalog()
    rules = _rules()
    owned = {title: qty for title, qty in _reference_deck().main.items()}
    owned["Karthus - Eternal"] = 0
    owned["Deathgrip"] = 4

    result = solve_wizard_deck(
        legend_title="LeBlanc - Deceiver",
        chosen_champion_title="LeBlanc - Fragmented",
        format_name="constructed",
        owned=owned,
        rules=rules,
        cards=catalog,
        reference_deck=_reference_deck(),
        current_deck=_reference_deck(),
    )

    assert result.deck.main.get("Karthus - Eternal", 0) == 0
    assert result.deck.main.get("Deathgrip", 0) <= rules.int_constraint("main_copy_limit", 3)
    assert result.deck.main.get("Deathgrip", 0) == 3
    assert validate_deck(result.deck, rules=rules, cards=catalog).is_valid
    assert result.validation.is_valid


def test_swap_karthus_to_deathgrip_preserves_three_copy_slot_max() -> None:
    catalog = _catalog()
    rules = _rules()
    deck = _reference_deck()
    deck.main["Deathgrip"] = 1
    deck.main["Mimic"] = 2
    owned = {"Deathgrip": 4, "Karthus - Eternal": 0}

    swapped = apply_wizard_main_swap(
        deck,
        "Karthus - Eternal",
        "Deathgrip",
        owned=owned,
        rules=rules,
        cards=catalog,
        strict_owned=True,
    )

    assert swapped.main.get("Karthus - Eternal", 0) == 0
    assert swapped.main.get("Deathgrip", 0) == 3
    assert swapped.main.get("Deathgrip", 0) <= rules.int_constraint("main_copy_limit", 3)


def test_lillia_iteration_two_fills_missing_cards_from_owned_collection_cluster() -> None:
    catalog = _lillia_catalog()
    rules = _rules()
    reference = _lillia_reference_deck()
    owned = {title: qty for title, qty in reference.main.items()}
    owned.update(
        {
            "Lillia - Bashful Bloom": 1,
            "Calm Rune": 6,
            "Mind Rune": 6,
            "Black Flame Altar": 1,
            "Dusk Rose Lab": 1,
            "Forbidding Waste": 1,
            "Heart of Dark Ice": 2,
            "Sprite Fountain": 0,
            "Smoke and Mirrors": 0,
            "Dream-Laden Bough": 3,
            "Sleepy Sprout": 3,
            "Gentle Bloom": 1,
        }
    )

    result = solve_wizard_deck(
        legend_title="Lillia - Bashful Bloom",
        chosen_champion_title="Lillia - Fae Fawn",
        format_name="constructed",
        owned=owned,
        rules=rules,
        cards=catalog,
        reference_deck=reference,
        current_deck=reference,
    )

    assert result.validation.is_valid
    assert result.metrics["isFullyOwned"]
    assert result.solver_status == "optimal"
    assert result.deck.main.get("Heart of Dark Ice", 0) <= 2
    assert result.deck.main.get("Sprite Fountain", 0) == 0
    assert result.deck.main.get("Smoke and Mirrors", 0) == 0
    assert sum(result.deck.main.values()) == rules.int_constraint("main_deck_size_exact", 40)
    assert sum(result.deck.main.get(title, 0) for title in ["Dream-Laden Bough", "Sleepy Sprout", "Gentle Bloom"]) == 7
    assert result.replacement_clusters
    cluster = result.replacement_clusters[0]
    assert {row["card"] for row in cluster["removed"]} >= {"Sprite Fountain", "Smoke and Mirrors", "Heart of Dark Ice"}
    assert sum(row["qty"] for row in cluster["added"]) == 7


def test_lillia_iteration_two_reports_infeasible_when_owned_pool_has_no_fillers() -> None:
    catalog = _lillia_catalog()
    rules = _rules()
    reference = _lillia_reference_deck()
    owned = {title: qty for title, qty in reference.main.items()}
    owned.update(
        {
            "Lillia - Bashful Bloom": 1,
            "Calm Rune": 6,
            "Mind Rune": 6,
            "Black Flame Altar": 1,
            "Dusk Rose Lab": 1,
            "Forbidding Waste": 1,
            "Heart of Dark Ice": 2,
            "Sprite Fountain": 0,
            "Smoke and Mirrors": 0,
        }
    )

    result = solve_wizard_deck(
        legend_title="Lillia - Bashful Bloom",
        chosen_champion_title="Lillia - Fae Fawn",
        format_name="constructed",
        owned=owned,
        rules=rules,
        cards=catalog,
        reference_deck=reference,
        current_deck=reference,
    )

    assert result.solver_status == "infeasible_owned_only"
    assert not result.validation.is_valid
    assert result.deck.main.get("Sprite Fountain", 0) == 0
    assert result.deck.main.get("Smoke and Mirrors", 0) == 0


def test_wizard_solve_endpoint_accepts_json_body() -> None:
    client = TestClient(app, raise_server_exceptions=False)
    response = client.post("/api/wizard/solve", json={"format": "constructed", "owned": {}})

    assert response.status_code == 200
    assert "solverStatus" in response.json()
