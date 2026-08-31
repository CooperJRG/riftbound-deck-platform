"""Legend matchups, and the claims they are allowed to make.

The arithmetic is easy and would survive any refactor. What these tests pin is the
*restraint*, and the one property unique to this table: it is an aggregate this project
did not compute, from matches it cannot inspect.

* a rate is never shown on a sample that cannot support one, and the refusal names the
  threshold it missed;
* "favourable" means the whole interval clears even -- never that the point estimate
  did, which is the failure that would let a 3-1 matchup read as a counter;
* ranking uses the interval bound, not the point estimate, so a lucky thin sample cannot
  outrank a measured one;
* a name the catalogue cannot resolve is dropped *and reported*, never dropped silently;
* symmetry is enforced, because it is the only audit available on somebody else's
  aggregate -- if a cell stops meaning what we think it means, this is where it shows.
"""

from __future__ import annotations

from conftest import make_card
from riftbound.domain.cards import build_catalog
from riftbound.domain.matchups import (
    MIN_EVENTS,
    MIN_MATCHES,
    WITHHELD_EVENTS,
    WITHHELD_MATCHES,
    build_matchups,
    symmetry_errors,
)

ENOUGH_EVENTS = MIN_EVENTS + 2


def _catalog():
    return build_catalog(
        [
            make_card("kennen-heart-of-the-tempest", "Kennen - Heart of the Tempest",
                      card_type="Legend"),
            make_card("irelia-blade-dancer", "Irelia - Blade Dancer", card_type="Legend"),
            make_card("azir-emperor-of-the-sands", "Azir - Emperor of the Sands",
                      card_type="Legend"),
        ]
    )


def _cell(legend, opponent, wins, losses, events=ENOUGH_EVENTS):
    return {
        "legend": legend, "opponent": opponent, "wins": wins, "losses": losses,
        "matches": wins + losses, "gamesWon": 0, "gamesLost": 0, "events": events,
    }


def _legend_row(name, wins, losses):
    return {
        "legend": name, "wins": wins, "losses": losses, "matches": wins + losses,
        "gamesWon": 0, "gamesLost": 0, "players": 10, "mirrorMatches": 0,
    }


def _build(cells, legends=()):
    table, notes = build_matchups(cells=cells, legends=legends, catalog=_catalog())
    return table, notes


# -- refusal ------------------------------------------------------------------


def test_a_thin_matchup_is_not_rated_and_says_why():
    table, _ = _build([_cell("Kennen - Heart of the Tempest", "Irelia - Blade Dancer", 5, 1)])
    row = table.matchups[0]
    assert not row.shown
    assert row.withheld == WITHHELD_MATCHES
    assert str(MIN_MATCHES) in row.explain_withheld()
    # The counts survive the refusal: "6 matches so far" is information, a blank is not.
    assert row.matches == 6 and row.wins == 5


def test_a_matchup_concentrated_in_too_few_events_is_not_rated():
    """Plenty of matches, nearly all at one tournament, is an anecdote about a Saturday."""
    table, _ = _build(
        [_cell("Kennen - Heart of the Tempest", "Irelia - Blade Dancer",
               MIN_MATCHES, 10, events=MIN_EVENTS - 1)]
    )
    row = table.matchups[0]
    assert not row.shown
    assert row.withheld == WITHHELD_EVENTS
    assert str(MIN_EVENTS) in row.explain_withheld()


def test_missing_event_counts_are_unknown_not_zero():
    """A source that ships no per-event breakdown must not fail every cell.

    ``events == 0`` means "the breakdown was absent", which is different from "this
    happened at no events" -- and withholding the whole table over a missing optional
    field would be the wrong way round.
    """
    table, _ = _build(
        [_cell("Kennen - Heart of the Tempest", "Irelia - Blade Dancer", 40, 30, events=0)]
    )
    assert table.matchups[0].shown


# -- what "favourable" is allowed to mean --------------------------------------


def test_favourable_requires_the_whole_interval_to_clear_even():
    """A point estimate above 50% is not an edge; a separated interval is."""
    # 60-40 over 100: the point estimate is 60%, but the interval still reaches below
    # 50%... or not. Either way, `favourable` must agree with the interval, never with
    # the point estimate alone.
    table, _ = _build([_cell("Kennen - Heart of the Tempest", "Irelia - Blade Dancer", 60, 40)])
    row = table.matchups[0]
    assert row.win_rate > 0.5
    assert row.favourable == (row.interval_low > 0.5)
    assert row.separated == (row.interval_low > 0.5 or row.interval_high < 0.5)


def test_a_coin_flip_is_never_called_an_edge():
    table, _ = _build([_cell("Kennen - Heart of the Tempest", "Irelia - Blade Dancer", 50, 50)])
    row = table.matchups[0]
    assert row.shown
    assert not row.separated and not row.favourable and not row.unfavourable


def test_an_unrated_matchup_is_never_separated():
    """`separated` gates on `shown`, so a 3-0 sample cannot claim an edge."""
    table, _ = _build([_cell("Kennen - Heart of the Tempest", "Irelia - Blade Dancer", 3, 0)])
    assert not table.matchups[0].separated


# -- ordering ------------------------------------------------------------------


def test_legends_rank_by_interval_bound_not_point_estimate():
    """A higher point estimate on a thin sample must not outrank a measured one.

    The numbers are chosen so the two orderings genuinely disagree, which is fussier
    than it sounds: 28-12 (70% over 40) has a *higher* Wilson bound than 550-450 (55%
    over 1,000), so it deserves to win and proves nothing. 18-12 is the real case --
    60% against 55% on the point estimate, 42% against 52% on the bound.
    """
    table, _ = _build(
        [],
        legends=[
            _legend_row("Irelia - Blade Dancer", 18, 12),          # 60%, n=30
            _legend_row("Kennen - Heart of the Tempest", 550, 450),  # 55%, n=1000
        ],
    )
    irelia = table.record("irelia-blade-dancer")
    kennen = table.record("kennen-heart-of-the-tempest")
    assert irelia.win_rate > kennen.win_rate, "premise: the thin sample looks better"
    assert irelia.interval_low < kennen.interval_low, "premise: but is worse evidenced"

    ranked = [r.legend_id for r in table.ranked()]
    assert ranked[0] == "kennen-heart-of-the-tempest", (
        "the higher point estimate won; ranking must use the lower interval bound"
    )


def test_unrated_legends_sort_after_every_rated_one():
    table, _ = _build(
        [],
        legends=[
            _legend_row("Irelia - Blade Dancer", 2, 1),          # far too thin
            _legend_row("Kennen - Heart of the Tempest", 60, 55),
        ],
    )
    ranked = table.ranked()
    assert ranked[0].shown and not ranked[-1].shown


def test_a_legends_spread_puts_the_hardest_matchup_first():
    table, _ = _build(
        [
            _cell("Kennen - Heart of the Tempest", "Irelia - Blade Dancer", 20, 60),
            _cell("Kennen - Heart of the Tempest", "Azir - Emperor of the Sands", 60, 20),
        ]
    )
    spread = table.for_legend("kennen-heart-of-the-tempest")
    assert spread[0].opponent_id == "irelia-blade-dancer"


# -- resolution ----------------------------------------------------------------


def test_an_unresolvable_legend_is_dropped_and_reported():
    """Silently missing and never-played look identical, and want opposite responses."""
    table, notes = _build(
        [_cell("Kennen - Heart of the Tempest", "Nobody - Who Is This", 40, 30)]
    )
    assert table.matchups == ()
    assert notes and "Nobody - Who Is This" in notes[0]


def test_names_resolve_to_card_ids_and_carry_the_catalogue_name():
    table, notes = _build(
        [_cell("Kennen, Heart of the Tempest", "Irelia, Blade Dancer", 40, 30)]
    )
    # Punctuation-insensitive: the source writes commas where the catalogue writes
    # dashes, and `Catalog.resolve` is the one place that difference is handled.
    assert not notes
    row = table.matchups[0]
    assert row.legend_id == "kennen-heart-of-the-tempest"
    assert row.opponent_name == "Irelia - Blade Dancer"


# -- integrity -----------------------------------------------------------------


def test_a_symmetric_matrix_passes():
    cells = [
        _cell("Kennen - Heart of the Tempest", "Irelia - Blade Dancer", 30, 20),
        _cell("Irelia - Blade Dancer", "Kennen - Heart of the Tempest", 20, 30),
    ]
    assert symmetry_errors(cells) == []


def test_an_asymmetric_matrix_is_reported():
    """If a cell stops counting what we think it counts, symmetry breaks first."""
    cells = [
        _cell("Kennen - Heart of the Tempest", "Irelia - Blade Dancer", 30, 20),
        _cell("Irelia - Blade Dancer", "Kennen - Heart of the Tempest", 25, 25),
    ]
    problems = symmetry_errors(cells)
    assert problems and "does not mirror" in problems[0]


def test_a_cell_with_no_opposing_cell_is_reported():
    cells = [_cell("Kennen - Heart of the Tempest", "Irelia - Blade Dancer", 30, 20)]
    problems = symmetry_errors(cells)
    assert problems and "no opposing cell" in problems[0]


# -- basis ---------------------------------------------------------------------


def test_the_basis_counts_what_was_measured_and_what_was_shown():
    table, _ = _build(
        [
            _cell("Kennen - Heart of the Tempest", "Irelia - Blade Dancer", 40, 30),
            _cell("Kennen - Heart of the Tempest", "Azir - Emperor of the Sands", 2, 1),
        ],
        legends=[_legend_row("Kennen - Heart of the Tempest", 60, 55)],
    )
    assert table.basis.cells_measured == 2
    assert table.basis.cells_shown == 1
    assert table.basis.legends_measured == 1
    # The bar has to be legible from the response alone; a client must never re-derive it.
    assert table.basis.min_matches == MIN_MATCHES
    assert table.basis.min_events == MIN_EVENTS


def test_an_empty_table_is_a_supported_state():
    """No matchup data at all is normal -- an old snapshot, or a failed fetch."""
    table, notes = _build([], legends=[])
    assert not table.available and notes == []
    assert table.ranked() == () and table.for_legend("kennen-heart-of-the-tempest") == ()
