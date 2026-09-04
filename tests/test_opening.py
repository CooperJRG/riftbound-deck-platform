"""Opening-hand odds.

The arithmetic has a closed form, so these are not "does it roughly work" tests -- they
check the properties a plausible-looking rewrite would break:

* the population is the **main deck only**. Runes and battlefields are separate zones
  and are never drawn; folding them in would deflate every number on the page by a
  third, and it would still look like a working feature.
* the rules come from the format profile, so a format that records none gets no
  simulator rather than another format's numbers wearing its name.
* "at least one of these" collapses the group instead of summing per card, so an
  early-play figure can never exceed 100%.
* the mulligan models bottoming, not shuffling -- a recycled card cannot come back.
"""

from __future__ import annotations

from math import comb, isclose

import pytest

from conftest import make_card
from riftbound.domain.cards import build_catalog
from riftbound.domain.deck import Deck
from riftbound.domain.opening import (
    at_least_one,
    at_least_one_of_any,
    hypergeometric,
    mulligan_odds,
    opening_odds,
    opening_rules,
)
from riftbound.domain.rules import BoundRules, FormatRules

HAND = 4


def _catalog():
    return build_catalog(
        [
            make_card("champ", "Champion Card", super_type="Champion", cost=3),
            make_card("one-drop", "One Drop", cost=1),
            make_card("two-drop", "Two Drop", cost=2),
            make_card("big", "Big Thing", cost=7),
            make_card("rune-card", "A Rune", card_type="Rune", cost=None),
            make_card("field", "A Battlefield", card_type="Battlefield", cost=None),
        ]
    )


def _rules(**constraints) -> BoundRules:
    base = {
        "opening_hand_size": HAND,
        "mulligan_max": 2,
        "mulligan_destination": "bottom",
        "draw_per_turn": 1,
    }
    base.update(constraints)
    return BoundRules(
        rules=FormatRules(
            format_name="constructed",
            description="",
            constraints=base,
            rule_refs={},
        ),
        banned_card_ids=frozenset(),
    )


def _deck(main: dict[str, int], **kw) -> Deck:
    return Deck.make(legend_id="legend", main=main, **kw)


# -- the distribution ----------------------------------------------------------


def test_hypergeometric_matches_the_closed_form():
    # 3 copies in 40, drawing 4, exactly 1.
    expected = comb(3, 1) * comb(37, 3) / comb(40, 4)
    assert isclose(hypergeometric(40, 3, 4, 1), expected, rel_tol=1e-12)


def test_the_distribution_sums_to_one():
    total = sum(hypergeometric(40, 3, 4, k) for k in range(0, 4))
    assert isclose(total, 1.0, rel_tol=1e-12)


def test_at_least_one_is_the_complement_of_none():
    assert isclose(at_least_one(40, 3, 4), 1 - hypergeometric(40, 3, 4, 0), rel_tol=1e-12)


@pytest.mark.parametrize(
    "population,successes,draws",
    [(0, 3, 4), (40, 0, 4), (40, 3, 0), (40, 3, -1)],
)
def test_degenerate_inputs_are_zero_not_an_error(population, successes, draws):
    assert at_least_one(population, successes, draws) == 0.0


def test_drawing_the_whole_deck_is_certain():
    assert at_least_one(40, 1, 40) == 1.0


def test_a_group_collapses_rather_than_summing():
    """Per-card addition double-counts hands holding two, and can exceed 100%."""
    # Twelve one-ofs: summing 12 x at_least_one(40,1,4) would give ~118%.
    naive = 12 * at_least_one(40, 1, 4)
    grouped = at_least_one_of_any(40, [1] * 12, 4)
    assert naive > 1.0
    assert grouped <= 1.0
    assert isclose(grouped, at_least_one(40, 12, 4), rel_tol=1e-12)


# -- the population is the main deck -------------------------------------------


def test_runes_and_battlefields_are_not_in_the_draw_population():
    """The single easiest way to get this whole feature quietly wrong."""
    main = {"one-drop": 3, "big": 37}
    deck = _deck(main, runes={"rune-card": 12}, battlefields=["field"])
    odds = opening_odds(deck, rules=_rules(), catalog=_catalog())

    assert odds.deck_size == 40, "runes or battlefields leaked into the population"
    row = next(r for r in odds.cards if r.card_id == "one-drop")
    assert isclose(row.opening, at_least_one(40, 3, HAND), rel_tol=1e-12)


# -- the rules come from the profile -------------------------------------------


def test_a_format_recording_no_hand_size_is_not_simulated():
    """Skirmish is deliberately in this state; it must not borrow constructed's numbers."""
    rules = _rules(opening_hand_size=0)
    odds = opening_odds(_deck({"one-drop": 40}), rules=rules, catalog=_catalog())
    assert not odds.rules.available
    assert not odds.available
    assert odds.cards == ()


def test_the_hand_size_is_read_from_the_profile_not_hardcoded():
    small = opening_odds(_deck({"one-drop": 3, "big": 37}),
                         rules=_rules(opening_hand_size=1), catalog=_catalog())
    large = opening_odds(_deck({"one-drop": 3, "big": 37}),
                         rules=_rules(opening_hand_size=7), catalog=_catalog())
    a = next(r for r in small.cards if r.card_id == "one-drop")
    b = next(r for r in large.cards if r.card_id == "one-drop")
    assert b.opening > a.opening


def test_by_turn_three_sees_the_hand_plus_two_draws():
    """Off by one here would overstate every "by turn N" figure on the page."""
    deck = _deck({"one-drop": 3, "big": 37})
    odds = opening_odds(deck, rules=_rules(draw_per_turn=1), catalog=_catalog())
    row = next(r for r in odds.cards if r.card_id == "one-drop")
    assert isclose(row.by_turn_three, at_least_one(40, 3, HAND + 2), rel_tol=1e-12)


def test_a_format_that_draws_nothing_per_turn_sees_only_its_opening_hand():
    deck = _deck({"one-drop": 3, "big": 37})
    odds = opening_odds(deck, rules=_rules(draw_per_turn=0), catalog=_catalog())
    row = next(r for r in odds.cards if r.card_id == "one-drop")
    assert isclose(row.by_turn_three, row.opening, rel_tol=1e-12)


# -- the deck's own summary ----------------------------------------------------


def test_the_chosen_champion_gets_its_own_row():
    deck = _deck({"champ": 1, "big": 39}, champion_id="champ")
    odds = opening_odds(deck, rules=_rules(), catalog=_catalog())
    assert odds.champion is not None
    assert isclose(odds.champion.opening, at_least_one(40, 1, HAND), rel_tol=1e-12)


def test_a_champion_not_in_the_main_deck_has_no_odds():
    """It cannot be drawn if it is not in the population."""
    deck = _deck({"big": 40}, champion_id="champ")
    assert opening_odds(deck, rules=_rules(), catalog=_catalog()).champion is None


def test_early_play_odds_never_exceed_one_and_rise_with_the_ceiling():
    deck = _deck({"one-drop": 4, "two-drop": 8, "big": 28})
    odds = opening_odds(deck, rules=_rules(), catalog=_catalog(), costs=(1, 2))
    by_cost = dict(odds.playable_by_cost)
    assert 0 < by_cost[1] < by_cost[2] <= 1.0


def test_an_empty_deck_is_reported_rather_than_dividing_by_zero():
    odds = opening_odds(_deck({}), rules=_rules(), catalog=_catalog())
    assert not odds.available and odds.deck_size == 0


# -- the mulligan --------------------------------------------------------------


def test_a_mulligan_can_only_improve_the_odds_of_finding_a_card():
    """You never bottom a copy of what you are digging for -- see the docstring."""
    plain = at_least_one(40, 3, HAND)
    after = mulligan_odds(40, 3, hand_size=HAND, recycled=2)
    assert after > plain


def test_recycling_nothing_is_the_plain_opening_hand():
    assert isclose(
        mulligan_odds(40, 3, hand_size=HAND, recycled=0),
        at_least_one(40, 3, HAND),
        rel_tol=1e-12,
    )


def test_bottomed_cards_cannot_come_back():
    """Bottoming, not shuffling: replacements come from cards never held.

    Modelled as shuffling, a deck whose every copy sat in the opening hand could draw
    one back. Bottoming makes that impossible, and with all copies in hand the player
    already has one anyway -- so the probability is exactly 1 either way here, and the
    property worth pinning is that replacements are drawn from `population - hand`.
    """
    # 4 copies, hand of 4: P(none in hand) is tiny but non-zero, and conditional on it
    # the replacements come from the 36 cards never seen.
    exact = 1 - hypergeometric(40, 4, 4, 0) * hypergeometric(36, 4, 2, 0)
    assert isclose(mulligan_odds(40, 4, hand_size=4, recycled=2), exact, rel_tol=1e-12)


def test_more_recycled_cards_never_lowers_the_odds():
    a = mulligan_odds(40, 2, hand_size=HAND, recycled=1)
    b = mulligan_odds(40, 2, hand_size=HAND, recycled=2)
    assert b >= a


def test_opening_rules_report_their_own_provenance():
    rules = opening_rules(_rules(), evidence="derived from guides", cited=False)
    assert rules.available and not rules.cited
    assert rules.evidence == "derived from guides"
    assert rules.mulligan_destination == "bottom"
