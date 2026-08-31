"""Placing a legend in the field it is actually in.

The arithmetic is a weighted mean. What these tests pin is the judgement around it:

* the weighting is by how often you *meet* an opponent, so a catastrophic matchup
  against a deck nobody plays does not drag the number down;
* unrated matchups are excluded and the coverage is reported, rather than being scored
  as even (flattering) or as zero (libellous);
* the boarding order is by cost, not by badness -- the single most important property
  here, and the one a well-meaning "sort by win rate" would quietly undo;
* nothing claims a card answers a matchup, because no source says so.
"""

from __future__ import annotations

from conftest import make_card
from riftbound.domain.cards import build_catalog
from riftbound.domain.field_plan import (
    MIN_SWING,
    field_outlook,
    field_shares,
    sideboard_plan,
)
from riftbound.domain.legend_index import LegendIndex
from riftbound.domain.matchups import MIN_EVENTS, MIN_MATCHES, build_matchups

POPULAR = "Kennen - Heart of the Tempest"
RARE = "Azir - Emperor of the Sands"
ME = "Irelia - Blade Dancer"

ENOUGH = MIN_EVENTS + 2


def _catalog():
    return build_catalog(
        [
            make_card("kennen-heart-of-the-tempest", POPULAR, card_type="Legend"),
            make_card("irelia-blade-dancer", ME, card_type="Legend"),
            make_card("azir-emperor-of-the-sands", RARE, card_type="Legend"),
        ]
    )


def _cell(legend, opponent, wins, losses, events=ENOUGH):
    return {
        "legend": legend, "opponent": opponent, "wins": wins, "losses": losses,
        "matches": wins + losses, "gamesWon": 0, "gamesLost": 0, "events": events,
    }


def _legend_row(name, wins, losses):
    return {
        "legend": name, "wins": wins, "losses": losses, "matches": wins + losses,
        "gamesWon": 0, "gamesLost": 0, "players": 10, "mirrorMatches": 0,
    }


def _table(cells, legends):
    catalog = _catalog()
    table, _ = build_matchups(cells=cells, legends=legends, catalog=catalog)
    return table, catalog


# -- shares --------------------------------------------------------------------


def test_shares_come_from_match_counts_and_sum_to_one():
    table, _ = _table(
        [],
        [_legend_row(POPULAR, 600, 400), _legend_row(RARE, 60, 40)],
    )
    shares = field_shares(table)
    assert abs(sum(shares.values()) - 1.0) < 1e-9
    assert shares["kennen-heart-of-the-tempest"] > shares["azir-emperor-of-the-sands"]


# -- the weighting ---------------------------------------------------------------


def test_a_disaster_against_a_rare_deck_barely_moves_the_number():
    """The whole point of weighting: rarity is a discount on a bad matchup."""
    legends = [
        _legend_row(ME, 500, 500),
        _legend_row(POPULAR, 900, 900),   # ~90% of the field
        _legend_row(RARE, 50, 50),        # ~10%
    ]
    even = _table(
        [
            _cell(ME, POPULAR, 50, 50),
            _cell(ME, RARE, 50, 50),
            _cell(POPULAR, ME, 50, 50),
            _cell(RARE, ME, 50, 50),
        ],
        legends,
    )
    disaster = _table(
        [
            _cell(ME, POPULAR, 50, 50),
            _cell(ME, RARE, 0, 100),      # unwinnable, but rare
            _cell(POPULAR, ME, 50, 50),
            _cell(RARE, ME, 100, 0),
        ],
        legends,
    )
    a = field_outlook("irelia-blade-dancer", table=even[0], catalog=even[1])
    b = field_outlook("irelia-blade-dancer", table=disaster[0], catalog=disaster[1])
    lost = a.expected_win_rate - b.expected_win_rate
    assert 0 < lost < 0.10, (
        "a 0% matchup against a tenth of the field should cost about five points, "
        f"not {lost:.1%}"
    )


def test_the_same_disaster_against_the_popular_deck_costs_far_more():
    legends = [
        _legend_row(ME, 500, 500),
        _legend_row(POPULAR, 900, 900),
        _legend_row(RARE, 50, 50),
    ]
    table, catalog = _table(
        [
            _cell(ME, POPULAR, 0, 100),   # unwinnable, and everywhere
            _cell(ME, RARE, 50, 50),
            _cell(POPULAR, ME, 100, 0),
            _cell(RARE, ME, 50, 50),
        ],
        legends,
    )
    outlook = field_outlook("irelia-blade-dancer", table=table, catalog=catalog)
    assert outlook.expected_win_rate < 0.15


# -- coverage --------------------------------------------------------------------


def test_unrated_matchups_are_excluded_and_the_coverage_says_so():
    """An unmeasured matchup must not be scored as even, nor as a loss."""
    legends = [
        _legend_row(ME, 500, 500),
        _legend_row(POPULAR, 900, 900),
        _legend_row(RARE, 50, 50),
    ]
    table, catalog = _table(
        [
            _cell(ME, POPULAR, 60, 40),
            # Too thin to rate at all.
            _cell(ME, RARE, 2, 1),
            _cell(POPULAR, ME, 40, 60),
            _cell(RARE, ME, 1, 2),
        ],
        legends,
    )
    outlook = field_outlook("irelia-blade-dancer", table=table, catalog=catalog)
    # Only the rated matchup counts, so the rate is that matchup's rate...
    assert abs(outlook.expected_win_rate - 0.6) < 1e-6
    # ...and the coverage admits it did not see the rest of the field.
    assert 0 < outlook.coverage < 1


def test_no_rated_matchups_is_not_shown_rather_than_zero():
    table, catalog = _table(
        [_cell(ME, POPULAR, 1, 1), _cell(POPULAR, ME, 1, 1)],
        [_legend_row(ME, 2, 2), _legend_row(POPULAR, 2, 2)],
    )
    outlook = field_outlook("irelia-blade-dancer", table=table, catalog=catalog)
    assert not outlook.shown and outlook.coverage == 0


# -- the boarding order ----------------------------------------------------------


def test_boarding_order_is_by_cost_not_by_how_badly_it_goes():
    """The property most likely to be undone by a well-meaning "sort by win rate"."""
    legends = [
        _legend_row(ME, 500, 500),
        _legend_row(POPULAR, 900, 900),   # ~90% of the field
        _legend_row(RARE, 50, 50),        # ~10%
    ]
    table, catalog = _table(
        [
            # Mediocre, but against nearly everybody.
            _cell(ME, POPULAR, 40, 60),
            # Far worse, but hardly ever met.
            _cell(ME, RARE, 10, 90),
            _cell(POPULAR, ME, 60, 40),
            _cell(RARE, ME, 90, 10),
        ],
        legends,
    )
    outlook = field_outlook("irelia-blade-dancer", table=table, catalog=catalog)
    order = outlook.boarding_order()
    assert order[0].opponent_id == "kennen-heart-of-the-tempest", (
        "the worse win rate was boarded for first; the order must be by cost"
    )
    assert order[0].win_rate > order[1].win_rate, "premise: the first one is less bad"


def test_a_matchup_too_cheap_to_matter_is_not_offered():
    legends = [
        _legend_row(ME, 500, 500),
        _legend_row(POPULAR, 9999, 9999),
        _legend_row(RARE, 20, 20),
    ]
    table, catalog = _table(
        [
            _cell(ME, POPULAR, 50, 50),
            _cell(ME, RARE, 20, 30),
            _cell(POPULAR, ME, 50, 50),
            _cell(RARE, ME, 30, 20),
        ],
        legends,
    )
    outlook = field_outlook("irelia-blade-dancer", table=table, catalog=catalog)
    for row in outlook.boarding_order():
        assert row.swing <= -MIN_SWING


def test_a_winning_matchup_is_never_a_boarding_target():
    legends = [_legend_row(ME, 500, 500), _legend_row(POPULAR, 900, 900)]
    table, catalog = _table(
        [_cell(ME, POPULAR, 90, 10), _cell(POPULAR, ME, 10, 90)], legends
    )
    outlook = field_outlook("irelia-blade-dancer", table=table, catalog=catalog)
    assert outlook.boarding_order() == ()


# -- the plan --------------------------------------------------------------------


def test_a_plan_reports_what_the_opponent_plays_and_never_an_answer():
    legends = [_legend_row(ME, 500, 500), _legend_row(POPULAR, 900, 900)]
    table, catalog = _table(
        [_cell(ME, POPULAR, 20, 80), _cell(POPULAR, ME, 80, 20)], legends
    )
    outlook, plans = sideboard_plan(
        "irelia-blade-dancer", table=table, index=LegendIndex(profiles={}), catalog=catalog
    )
    assert outlook.shown
    assert len(plans) == 1
    plan = plans[0]
    assert plan.matchup.opponent_id == "kennen-heart-of-the-tempest"
    # No index, so no threats -- and crucially, no invented "counter" either. The plan
    # carries what the opponent plays or nothing, never a card claimed to beat them.
    assert plan.threats == ()
    assert not hasattr(plan, "answers")


def test_no_matchup_table_yields_no_plan_rather_than_an_error():
    table, catalog = _table([], [])
    outlook, plans = sideboard_plan(
        "irelia-blade-dancer", table=table, index=LegendIndex(profiles={}), catalog=catalog
    )
    assert not outlook.shown and plans == ()


def test_the_floor_constants_are_the_matchup_modules_own():
    """The plan must never publish a matchup the matchup module would withhold."""
    legends = [_legend_row(ME, 500, 500), _legend_row(POPULAR, 900, 900)]
    table, catalog = _table(
        [
            _cell(ME, POPULAR, MIN_MATCHES // 2, 0, events=ENOUGH),
            _cell(POPULAR, ME, 0, MIN_MATCHES // 2, events=ENOUGH),
        ],
        legends,
    )
    outlook = field_outlook("irelia-blade-dancer", table=table, catalog=catalog)
    assert not outlook.shown
