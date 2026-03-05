from __future__ import annotations

from app.domain.analysis import analyze_collection_completion
from app.domain.models import DeckPayload
from app.domain.normalization import normalize_card_key
from app.infra.cards_repo import CardCatalog, CardRecord


def _card(
    title: str,
    card_type: str,
    *,
    super_type: str = "",
    tags: tuple[str, ...] | None = None,
    champion_tags: tuple[str, ...] = (),
    domains: tuple[str, ...] = ("Mind",),
    cost: int | None = 2,
    might: int | None = 2,
    effect: str = "",
    is_unique: bool = False,
) -> CardRecord:
    tags_resolved = tags if tags is not None else champion_tags
    return CardRecord(
        title=title,
        card_type=card_type,
        super_type=super_type,
        tags=tags_resolved,
        champion_tags=champion_tags,
        domains=domains,
        domain_parse_ok=True,
        cost=cost,
        might=might,
        image_url="",
        is_unique=is_unique,
        effect=effect,
    )


def _catalog() -> CardCatalog:
    cards = [
        _card("Legend A", "Legend", champion_tags=("A",), domains=("Mind",)),
        _card("Champion A", "Unit", super_type="Champion", champion_tags=("A",), domains=("Mind",)),
        _card("Draven - Glorious Executioner", "Legend", champion_tags=("Draven",), domains=("Fury", "Chaos")),
        _card("Draven - Reckless", "Unit", super_type="Champion", champion_tags=("Draven",), domains=("Fury",)),
        _card("Mind Spell A", "Spell", domains=("Mind",), cost=2, might=0, effect="Draw 2 cards."),
        _card("Mind Spell B", "Spell", domains=("Mind",), cost=2, might=0, effect="Draw 2 cards."),
        _card("Mind Spell C", "Spell", domains=("Mind",), cost=6, might=0, effect="Deal 5 damage."),
        _card("Fury Spell A", "Spell", domains=("Fury",), effect="Deal 2 damage."),
        _card("Fury Spell B", "Spell", domains=("Fury",), effect="Deal 2 damage."),
        _card("Chaos Spell B", "Spell", domains=("Chaos",), effect="Deal 2 damage."),
        _card("Chaos Spell Z", "Spell", domains=("Chaos",), effect="Deal 6 damage."),
        _card("Draven Signature Blast", "Spell", super_type="Signature", champion_tags=("Draven",), domains=("Fury",), effect="Deal 3 damage."),
        _card("Chaos Signature Echo", "Spell", super_type="Signature", champion_tags=("Draven",), domains=("Chaos",), effect="Deal 3 damage."),
        _card("Fury Barrage", "Spell", domains=("Fury",), effect="Deal 3 damage."),
        _card("Chaos Ambush", "Spell", domains=("Chaos",), effect="Deal 3 damage."),
    ]
    by_title = {c.title: c for c in cards}
    by_key = {normalize_card_key(c.title): c for c in cards}
    return CardCatalog(cards=tuple(cards), by_title=by_title, by_key=by_key)


def test_collection_analysis_reports_missing_cards() -> None:
    deck = DeckPayload(
        name="Deck A",
        legendTitle="Legend A",
        chosenChampionTitle="Champion A",
        main={"Champion A": 1, "Spell A": 3, "Unit A": 3},
        runes={"Mind Rune": 12},
        battlefields=["Field A", "Field B", "Field C"],
        sideboard={},
    )
    collection = {
        "Legend A": 1,
        "Champion A": 1,
        "Spell A": 1,
        "Mind Rune": 12,
        "Field A": 1,
    }
    result = analyze_collection_completion(deck, collection=collection)
    assert result.is_buildable is False
    assert result.missing_copies > 0
    assert any(row.card == "Spell A" and row.missing == 2 for row in result.missing_cards)


def test_collection_analysis_includes_legal_replacement_suggestions() -> None:
    deck = DeckPayload(
        name="Deck Replace",
        legendTitle="Legend A",
        chosenChampionTitle="Champion A",
        main={"Champion A": 1, "Mind Spell A": 3},
        runes={},
        battlefields=[],
        sideboard={},
    )
    collection = {
        "Legend A": 1,
        "Champion A": 1,
        "Mind Spell B": 2,
        "Mind Spell C": 1,
        "Chaos Spell Z": 4,
    }
    result = analyze_collection_completion(deck, collection=collection, cards=_catalog())
    assert any(row.card == "Mind Spell A" and row.missing == 3 for row in result.missing_cards)

    suggestion = next((row for row in result.replacement_suggestions if row.card == "Mind Spell A"), None)
    assert suggestion is not None
    option_titles = [opt.card for opt in suggestion.options]
    assert "Mind Spell B" in option_titles
    assert "Mind Spell C" in option_titles
    assert "Chaos Spell Z" not in option_titles


def test_replacements_for_dual_domain_legend_consider_both_domains() -> None:
    catalog = _catalog()
    deck = DeckPayload(
        name="Dual Domain Replace",
        legendTitle="Draven - Glorious Executioner",
        chosenChampionTitle="Draven - Reckless",
        main={"Draven - Reckless": 1, "Fury Spell A": 3},
        runes={},
        battlefields=[],
        sideboard={},
    )
    collection = {
        "Draven - Glorious Executioner": 1,
        "Draven - Reckless": 1,
        "Fury Spell B": 2,
        "Chaos Spell B": 2,
    }
    result = analyze_collection_completion(deck, collection=collection, cards=catalog)
    suggestion = next((row for row in result.replacement_suggestions if row.card == "Fury Spell A"), None)
    assert suggestion is not None
    assert suggestion.options

    option_domains = []
    for opt in suggestion.options:
        card = catalog.by_title.get(opt.card)
        if card is not None:
            option_domains.append(set(card.domains))
    assert any("Fury" in domains for domains in option_domains)
    assert any("Chaos" in domains for domains in option_domains)


def test_signature_missing_cards_use_non_signature_replacements_from_both_legend_domains() -> None:
    catalog = _catalog()
    deck = DeckPayload(
        name="Signature Replace",
        legendTitle="Draven - Glorious Executioner",
        chosenChampionTitle="Draven - Reckless",
        main={"Draven - Reckless": 1, "Draven Signature Blast": 2},
        runes={},
        battlefields=[],
        sideboard={},
    )
    collection = {
        "Draven - Glorious Executioner": 1,
        "Draven - Reckless": 1,
        "Fury Barrage": 2,
        "Chaos Ambush": 2,
        "Chaos Signature Echo": 3,
    }
    result = analyze_collection_completion(deck, collection=collection, cards=catalog)
    suggestion = next((row for row in result.replacement_suggestions if row.card == "Draven Signature Blast"), None)
    assert suggestion is not None
    option_titles = [opt.card for opt in suggestion.options]
    assert "Fury Barrage" in option_titles
    assert "Chaos Ambush" in option_titles
    assert "Chaos Signature Echo" not in option_titles


def test_similarity_prefers_closer_effect_and_cost_matches() -> None:
    deck = DeckPayload(
        name="Similarity Rank",
        legendTitle="Legend A",
        chosenChampionTitle="Champion A",
        main={"Champion A": 1, "Mind Spell A": 2},
        runes={},
        battlefields=[],
        sideboard={},
    )
    collection = {
        "Legend A": 1,
        "Champion A": 1,
        "Mind Spell B": 2,
        "Mind Spell C": 2,
    }
    result = analyze_collection_completion(deck, collection=collection, cards=_catalog())
    suggestion = next((row for row in result.replacement_suggestions if row.card == "Mind Spell A"), None)
    assert suggestion is not None
    assert suggestion.options
    assert suggestion.options[0].card == "Mind Spell B"


def test_collection_analysis_completion_cost_uses_cheapest_price_and_buy_link() -> None:
    deck = DeckPayload(
        name="Deck Cost",
        legendTitle="Legend A",
        chosenChampionTitle="Champion A",
        main={"Champion A": 1, "Mind Spell A": 3},
        runes={},
        battlefields=[],
        sideboard={},
    )
    collection = {
        "Legend A": 1,
        "Champion A": 1,
        "Mind Spell A": 1,
    }
    price_map = {
        "mindspella": 1.95,
        # Simulate another print/version; completion should use cheapest available.
        "mindspellaprintb": 2.75,
    }

    def unit_price_for_title(title: str) -> float | None:
        key = normalize_card_key(title)
        if key == "mindspella":
            return min(1.95, 2.75)
        return price_map.get(key)

    def buy_url_for_title(title: str) -> str:
        return f"https://www.tcgplayer.com/search/all/product?q={title}"

    result = analyze_collection_completion(
        deck,
        collection=collection,
        cards=_catalog(),
        unit_price_for_title=unit_price_for_title,
        buy_url_for_title=buy_url_for_title,
    )
    missing_row = next((row for row in result.missing_cards if row.card == "Mind Spell A"), None)
    assert missing_row is not None
    assert missing_row.missing == 2
    assert missing_row.estimated_unit_price == 1.95
    assert missing_row.estimated_missing_cost == 3.9
    assert "tcgplayer.com/search/all/product" in missing_row.tcgplayer_url
    assert result.estimated_completion_cost == 3.9
    assert result.missing_cards_priced == 1
    assert result.missing_cards_unpriced == 0
