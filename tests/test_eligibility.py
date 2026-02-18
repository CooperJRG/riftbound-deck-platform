from __future__ import annotations

from pathlib import Path

from app.domain.eligibility import build_eligibility_snapshot
from app.domain.normalization import normalize_card_key
from app.domain.rules import load_format_rules
from app.infra.cards_repo import CardCatalog, CardRecord


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
        _card("Ezreal - Prodigal Explorer", "Legend", champion_tags=("Ezreal",), domains=("Mind", "Order")),
        _card("Annie - Incendiary", "Legend", champion_tags=("Annie",), domains=("Chaos",)),
        _card("Ezreal - Prodigy", "Unit", super_type="Champion", champion_tags=("Ezreal",), domains=("Mind",)),
        _card("Annie - Fiery", "Unit", super_type="Champion", champion_tags=("Annie",), domains=("Chaos",)),
        _card("Mind Rune", "Rune", domains=("Mind",)),
        _card("Order Rune", "Rune", domains=("Order",)),
        _card("Chaos Rune", "Rune", domains=("Chaos",)),
        _card("Hall of Insights", "Battlefield", domains=("Mind",)),
        _card("Order Citadel", "Battlefield", domains=("Order",)),
        _card("Chaos Pit", "Battlefield", domains=("Chaos",)),
    ]
    by_title = {c.title: c for c in cards}
    by_key = {normalize_card_key(c.title): c for c in cards}
    return CardCatalog(cards=tuple(cards), by_title=by_title, by_key=by_key)


def _rules():
    profile_path = Path(__file__).resolve().parents[1] / "rules_profiles" / "constructed.json"
    return load_format_rules(profile_path)


def test_champion_options_match_selected_legend_tag() -> None:
    snapshot = build_eligibility_snapshot(
        cards=_catalog(),
        rules=_rules(),
        legend_title="Ezreal - Prodigal Explorer",
        limit=100,
    )
    titles = {card.title for card in snapshot.champions}
    assert "Ezreal - Prodigy" in titles
    assert "Annie - Fiery" not in titles


def test_rune_recommendation_matches_target_total() -> None:
    snapshot = build_eligibility_snapshot(
        cards=_catalog(),
        rules=_rules(),
        legend_title="Ezreal - Prodigal Explorer",
        limit=100,
    )
    assert sum(snapshot.recommended_runes.values()) == snapshot.rune_deck_size
    assert set(snapshot.recommended_runes.keys()).issubset({card.title for card in snapshot.runes})
