"""Focused tests for recommendations that do not belong in the legend index."""

from tests.conftest import make_card

from riftbound.domain.cards import build_catalog
from riftbound.domain.deck import Deck
from riftbound.domain.legend_index import LegendProfile
from riftbound.domain.meta import MetaDeck, Provenance
from riftbound.domain.suggest import (
    main_deck_suggestions,
    rune_suggestion_reason,
    sideboard_suggestions,
)


def _published(deck, slug: str, sideboard: dict[str, int]) -> MetaDeck:
    return MetaDeck(
        deck=deck.with_meta(sideboard=sideboard),
        provenance=Provenance(source="test", source_slug=slug, url=""),
    )


def test_sideboard_suggestions_come_from_published_sideboards(
    legal_deck, catalog, bound_rules,
):
    decks = [
        _published(legal_deck, "first", {"filler-10": 2, "filler-11": 1}),
        _published(legal_deck, "second", {"filler-10": 2, "filler-12": 2}),
    ]

    rows = sideboard_suggestions(
        legal_deck, decks, {"first": 2.0, "second": 1.0}, catalog, bound_rules
    )

    assert rows[0].card_id == "filler-10"
    assert rows[0].copies == 2
    assert rows[0].reason == "in 100% of comparable sideboards"


def test_sideboard_suggestions_respect_the_combined_copy_limit(
    legal_deck, catalog, bound_rules,
):
    published = _published(legal_deck, "field", {"filler-10": 2})
    player = legal_deck.with_meta(main={**legal_deck.main, "filler-10": 3})

    rows = sideboard_suggestions(
        player, [published], {"field": 1.0}, catalog, bound_rules
    )

    assert all(row.card_id != "filler-10" for row in rows)


def test_sideboard_suggestions_do_not_offer_more_of_a_card_already_chosen(
    legal_deck, catalog, bound_rules,
):
    published = _published(legal_deck, "field", {"filler-10": 2})
    player = legal_deck.with_meta(sideboard={"filler-10": 1})

    rows = sideboard_suggestions(
        player, [published], {"field": 1.0}, catalog, bound_rules
    )

    assert all(row.card_id != "filler-10" for row in rows)


def test_main_suggestions_do_not_top_up_a_partial_stack(catalog, bound_rules):
    profile = LegendProfile(
        legend_id="vi-piltover-enforcer",
        deck_count=1,
        play_rate={"filler-10": 1.0},
        copies={"filler-10": 3},
        clusters=(),
    )
    player = Deck.make(
        legend_id="vi-piltover-enforcer",
        main={"filler-10": 1},
    )

    rows = main_deck_suggestions(player, profile, catalog, bound_rules)

    assert all(row.card_id != "filler-10" for row in rows)


def _three_copy_profile() -> LegendProfile:
    return LegendProfile(
        legend_id="vi-piltover-enforcer",
        deck_count=1,
        play_rate={"filler-10": 1.0},
        copies={"filler-10": 3},
        clusters=(),
    )


def test_main_suggestion_quantity_fits_the_last_open_slot(catalog, bound_rules):
    player = Deck.make(
        legend_id="vi-piltover-enforcer",
        main={"already-chosen": 39},
    )

    rows = main_deck_suggestions(player, _three_copy_profile(), catalog, bound_rules)

    assert rows[0].card_id == "filler-10"
    assert rows[0].copies == 1


def test_main_suggestion_quantity_fits_two_open_slots(catalog, bound_rules):
    player = Deck.make(
        legend_id="vi-piltover-enforcer",
        main={"already-chosen": 38},
    )

    rows = main_deck_suggestions(player, _three_copy_profile(), catalog, bound_rules)

    assert rows[0].copies == 2


def test_full_main_deck_has_no_add_suggestions(catalog, bound_rules):
    player = Deck.make(
        legend_id="vi-piltover-enforcer",
        main={"already-chosen": 40},
    )

    assert main_deck_suggestions(
        player, _three_copy_profile(), catalog, bound_rules
    ) == []


def test_sideboard_suggestion_quantity_fits_remaining_capacity(
    legal_deck, catalog, bound_rules,
):
    published = _published(legal_deck, "field", {"filler-10": 3})
    player = legal_deck.with_meta(sideboard={"already-chosen": 7})

    rows = sideboard_suggestions(
        player, [published], {"field": 1.0}, catalog, bound_rules
    )

    assert rows[0].copies == 1


def test_missing_published_sideboards_are_not_counted_as_empty_data(
    legal_deck, catalog, bound_rules,
):
    rows = sideboard_suggestions(
        legal_deck,
        [_published(legal_deck, "missing", {}), _published(legal_deck, "known", {"filler-11": 1})],
        {"missing": 50.0, "known": 1.0},
        catalog,
        bound_rules,
    )

    assert rows[0].reason == "in 100% of comparable sideboards"


# -- rune_suggestion_reason ----------------------------------------------------


def _power_catalog():
    """A legend in two domains, and one card in each that actually demands power --
    unlike the shared `catalog` fixture's filler, which carries no power at all and so
    cannot exercise the "peak power requirements" branch of the explanation."""
    cards = [
        make_card(
            "a-legend", "A Legend", card_type="Legend",
            domains=("Fury", "Calm"), cost=None, might=None,
        ),
        make_card("fury-rune", "Fury Rune", card_type="Rune", domains=("Fury",), cost=None, might=None),
        make_card("calm-rune", "Calm Rune", card_type="Rune", domains=("Calm",), cost=None, might=None),
        make_card("fury-demand", "Fury Demand", domains=("Fury",), power=3, cost=4),
        make_card("calm-demand", "Calm Demand", domains=("Calm",), power=1, cost=2),
        make_card("no-power", "No Power", domains=("Fury",)),
    ]
    return build_catalog(cards)


def test_no_suggestion_asks_for_a_legend_first():
    assert rune_suggestion_reason(
        Deck.make(), {}, _power_catalog()
    ) == "Choose a legend to see a rune plan."


def test_an_empty_main_deck_is_named_as_temporary():
    """Before there are cards to read power from, the split is confessed as a
    placeholder rather than presented with the same confidence as a computed one."""
    reason = rune_suggestion_reason(
        Deck.make(legend_id="a-legend"),
        {"fury-rune": 6, "calm-rune": 6},
        _power_catalog(),
    )
    assert reason.startswith("A temporary even split across the legend's domains: ")
    assert "6 Fury Rune" in reason
    assert "6 Calm Rune" in reason
    assert "refresh it from their power requirements" in reason


def test_a_built_deck_cites_its_own_peak_power_demand():
    deck = Deck.make(legend_id="a-legend", main={"fury-demand": 3, "calm-demand": 2})
    reason = rune_suggestion_reason(
        deck, {"fury-rune": 8, "calm-rune": 4}, _power_catalog()
    )
    assert reason.startswith("Suggested from this deck's domain demand: 8 Fury Rune, 4 Calm Rune.")
    assert "Fury 3" in reason
    assert "Calm 1" in reason


def test_a_deck_with_no_power_demand_gets_no_floor_clause():
    """No card in the list asks for power, so nothing is claimed about preserving it."""
    deck = Deck.make(legend_id="a-legend", main={"no-power": 3})
    reason = rune_suggestion_reason(
        deck, {"fury-rune": 12}, _power_catalog()
    )
    assert reason == "Suggested from this deck's domain demand: 12 Fury Rune."


def test_a_rune_id_the_catalogue_no_longer_carries_still_reads():
    """The explanation must not crash, or silently drop the entry, when a suggested
    card has left the catalogue between suggestion and render."""
    reason = rune_suggestion_reason(
        Deck.make(legend_id="a-legend", main={"fury-demand": 3}),
        {"vanished-rune": 12},
        _power_catalog(),
    )
    assert "12 vanished-rune" in reason
