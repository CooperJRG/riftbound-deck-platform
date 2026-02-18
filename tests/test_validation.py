from __future__ import annotations

from pathlib import Path

from app.domain.models import DeckPayload
from app.domain.rules import load_format_rules
from app.domain.validator import validate_deck
from app.domain.normalization import normalize_card_key, strip_starter_suffix
from app.infra.cards_repo import CardCatalog, CardRecord


def _card(
    title: str,
    card_type: str,
    super_type: str = "",
    champion_tags: tuple[str, ...] = (),
    domains: tuple[str, ...] = ("Mind",),
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
    )


def _catalog() -> CardCatalog:
    non_champion_main_cards = [
        "Mind Adept",
        "Arcane Bolt",
        "Focus Gear",
        "Scholar's Insight",
        "Mystic Guard",
        "Runebound Blade",
        "Tactical Shift",
        "Arc Reactor",
        "Crystal Scout",
        "Ward of Order",
        "Psionic Echo",
        "Mirror Image",
        "Arcane Relay",
    ]
    cards: list[CardRecord] = [
        _card("Ezreal - Prodigal Explorer", "Legend", champion_tags=("Ezreal",)),
        _card("Ezreal - Prodigy", "Unit", super_type="Champion", champion_tags=("Ezreal",)),
        _card("Annie - Fiery", "Unit", super_type="Champion", champion_tags=("Annie",)),
        _card("Mind Rune", "Rune"),
        _card("Hall of Legends", "Battlefield"),
        _card("Forgotten Monument", "Battlefield"),
        _card("Skyline Rift", "Battlefield"),
    ]
    for name in non_champion_main_cards:
        card_type = "Spell"
        if "Gear" in name or "Blade" in name or "Reactor" in name:
            card_type = "Gear"
        elif "Adept" in name or "Guard" in name or "Scout" in name:
            card_type = "Unit"
        cards.append(_card(name, card_type))
    cards.append(_card("Colorless Relic", "Gear", domains=tuple()))

    by_title = {c.title: c for c in cards}
    by_key = {normalize_card_key(c.title): c for c in cards}
    return CardCatalog(cards=tuple(cards), by_title=by_title, by_key=by_key)


def _rules():
    profile_path = Path(__file__).resolve().parents[1] / "rules_profiles" / "constructed.json"
    return load_format_rules(profile_path)


def _valid_deck() -> DeckPayload:
    main = {
        "Ezreal - Prodigy": 1,
        "Mind Adept": 3,
        "Arcane Bolt": 3,
        "Focus Gear": 3,
        "Scholar's Insight": 3,
        "Mystic Guard": 3,
        "Runebound Blade": 3,
        "Tactical Shift": 3,
        "Arc Reactor": 3,
        "Crystal Scout": 3,
        "Ward of Order": 3,
        "Psionic Echo": 3,
        "Mirror Image": 3,
        "Arcane Relay": 3,
    }
    return DeckPayload(
        name="Valid Mind Deck",
        source="test",
        format="constructed",
        legendTitle="Ezreal - Prodigal Explorer",
        chosenChampionTitle="Ezreal - Prodigy",
        main=main,
        runes={"Mind Rune": 12},
        battlefields=["Hall of Legends", "Forgotten Monument", "Skyline Rift"],
        sideboard={},
    )


def test_constructed_valid_deck_passes() -> None:
    result = validate_deck(_valid_deck(), rules=_rules(), cards=_catalog())
    assert result.is_valid, result.model_dump()


def test_catalog_resolves_starter_alias() -> None:
    catalog = _catalog()
    assert catalog.resolve_title("Ezreal - Prodigal Explorer - Starter") == "Ezreal - Prodigal Explorer"


def test_catalog_strips_starter_suffix_for_unknown_titles() -> None:
    catalog = _catalog()
    assert catalog.resolve_title("Unknown Legend - Starter") == "Unknown Legend"


def test_starter_suffix_is_ignored_for_key_normalization() -> None:
    assert normalize_card_key("Annie - Dark Child") == normalize_card_key("Annie - Dark Child - Starter")
    assert strip_starter_suffix("Annie - Dark Child - Starter") == "Annie - Dark Child"


def test_invalid_main_size_fails() -> None:
    deck = _valid_deck()
    deck.main["Arcane Relay"] = 2
    result = validate_deck(deck, rules=_rules(), cards=_catalog())
    assert result.is_valid is False
    assert any(issue.code == "MAIN_DECK_SIZE" for issue in result.issues)


def test_champion_tag_mismatch_fails() -> None:
    deck = _valid_deck()
    deck.chosen_champion_title = "Annie - Fiery"
    deck.main["Annie - Fiery"] = 1
    deck.main["Arcane Relay"] = 2
    result = validate_deck(deck, rules=_rules(), cards=_catalog())
    assert result.is_valid is False
    assert any(issue.code == "CHAMPION_TAG" for issue in result.issues)


def test_domainless_main_card_fails_domain_identity() -> None:
    deck = _valid_deck()
    deck.main["Colorless Relic"] = 1
    deck.main["Arcane Relay"] = 2
    result = validate_deck(deck, rules=_rules(), cards=_catalog())
    assert result.is_valid is False
    assert any(issue.code == "MAIN_DOMAIN" for issue in result.issues)
