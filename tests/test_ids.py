"""Card identity. Every case here is drawn from the real upstream export."""

from __future__ import annotations

import pytest

from riftbound.domain.ids import card_id_for, oracle_name, print_id_for, search_key


@pytest.mark.parametrize(
    "title,expected",
    [
        ("Caitlyn - Patrolling (Chinese Arcane Box Set Promo)", "Caitlyn - Patrolling"),
        ("Buff (TFT Promo)", "Buff"),
        ("Body Rune (Origins Nexus Night Promo)", "Body Rune"),
        ("Some Card - Starter", "Some Card"),
        ("Plain Card", "Plain Card"),
    ],
)
def test_oracle_name_strips_printing_decoration(title, expected):
    assert oracle_name(title) == expected


def test_dash_and_comma_spellings_are_the_same_card():
    """Upstream lists ogn-067 as "Blitzcrank - Impassive" and ogn-067-P as
    "Blitzcrank, Impassive". They are one card and must share an id."""
    assert card_id_for("Blitzcrank - Impassive") == card_id_for("Blitzcrank, Impassive")
    assert card_id_for("Darius - Hand of Noxus") == card_id_for("Darius, Hand of Noxus")


def test_apostrophes_collapse_rather_than_split():
    assert card_id_for("Kai'Sa - Daughter of the Void") == "kaisa-daughter-of-the-void"
    assert card_id_for("Kai'Sa, Daughter of the Void") == "kaisa-daughter-of-the-void"


def test_curly_and_straight_quotes_agree():
    assert card_id_for("Kai’Sa - Daughter of the Void") == card_id_for(
        "Kai'Sa - Daughter of the Void"
    )


def test_en_dash_and_hyphen_agree():
    assert card_id_for("Vi – Destructive") == card_id_for("Vi - Destructive")


def test_promo_and_base_printings_share_a_card_id_but_not_a_print_id():
    base = print_id_for("ogn-068-caitlyn-patrolling")
    showcase = print_id_for("ogn-068a-caitlyn-patrolling")
    assert base != showcase
    assert card_id_for("Caitlyn - Patrolling") == card_id_for(
        "Caitlyn - Patrolling (Chinese Arcane Box Set Promo)"
    )


def test_empty_input_yields_empty_id():
    assert card_id_for("") == ""
    assert card_id_for(None) == ""
    assert oracle_name(None) == ""


def test_print_id_falls_back_to_title_when_slug_missing():
    assert print_id_for("", fallback_title="Vi - Destructive") == "vi-destructive"


def test_search_key_ignores_punctuation_and_case():
    assert search_key("Kai'Sa - Daughter of the Void") == search_key("kaisa daughter of the void")
