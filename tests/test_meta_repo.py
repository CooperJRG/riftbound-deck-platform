from __future__ import annotations

import json
from pathlib import Path

from app.domain.normalization import normalize_card_key
from app.domain.rules import FormatRules
from app.infra.cards_repo import CardCatalog, CardRecord
from app.infra.meta_repo import MetaDeckRepository


def _card(
    title: str,
    card_type: str,
    *,
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
        cost=1,
        might=1,
        image_url="",
    )


def _catalog() -> CardCatalog:
    cards = [
        _card("Legend A", "Legend", champion_tags=("A",), domains=("Mind",)),
        _card("Champion A", "Unit", super_type="Champion", champion_tags=("A",), domains=("Mind",)),
        _card("Mind Spell", "Spell", domains=("Mind",)),
        _card("Mind Rune", "Rune", domains=("Mind",)),
        _card("Mind Field", "Battlefield", domains=("Mind",)),
    ]
    by_title = {c.title: c for c in cards}
    by_key = {normalize_card_key(c.title): c for c in cards}
    return CardCatalog(cards=tuple(cards), by_title=by_title, by_key=by_key)


def _rules() -> FormatRules:
    return FormatRules(
        format_name="constructed",
        description="test",
        source_of_truth=tuple(),
        constraints={
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
            "sideboard_max": 8,
            "signature_max_total": 3,
            "domain_identity_enforced": True,
            "rune_card_type": "Rune",
            "battlefield_card_type": "Battlefield",
            "allowed_main_card_types": ["Unit", "Gear", "Spell"],
            "allowed_sideboard_card_types": ["Unit", "Gear", "Spell"],
        },
        rule_refs={},
    )


def _write_meta(path: Path) -> None:
    rows = [
        {
            "source": "ogs",
            "id": "valid-1",
            "name": "Valid Meta Deck",
            "leaderTitle": "Legend A - Starter",
            "cards": {
                "Champion A": 1,
                "Mind Spell": 1,
                "Mind Rune": 1,
                "Mind Field": 1,
            },
        },
        {
            "source": "ogs",
            "id": "invalid-1",
            "name": "Invalid Meta Deck",
            "leaderTitle": "Legend A - Starter",
            "cards": {
                "Champion A": 1,
                "Mind Spell": 1,
                "Mind Field": 1,
            },
        },
    ]
    path.write_text(json.dumps(rows), encoding="utf-8")


def test_meta_repo_filters_out_illegal_decks(tmp_path: Path) -> None:
    meta_path = tmp_path / "meta.json"
    _write_meta(meta_path)
    repo = MetaDeckRepository(meta_path, _catalog(), _rules())

    decks = repo.list_decks(limit=20)
    assert len(decks) == 1
    assert decks[0].deck_id == "valid-1"
    assert decks[0].leader_title == "Legend A"
    assert decks[0].deck.legend_title == "Legend A"

