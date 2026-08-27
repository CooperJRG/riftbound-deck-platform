"""Trend aggregation, and the claims it is allowed to make.

This is the module most able to lie. It turns a few hundred published decklists into
percentages and arrows, and a percentage is believed in a way a deck list is not --
which is exactly how v2 ended up presenting a model's guess as a fact.

So the tests here are mostly about *denominators and restraint* rather than arithmetic:

* a share is measured against published lists, never against the attendance of events
  whose lists nobody published;
* an incomplete or unresolved deck is dropped, never counted as a zero;
* movement is refused when the sample cannot support it, rather than shown small;
* coverage cannot exceed 1.0 however the upstream counts.

The arithmetic is easy and would survive any refactor. These properties are the ones a
well-meaning change breaks.
"""

from __future__ import annotations

from datetime import date

import pytest

from riftbound.domain.deck import Deck
from riftbound.domain.meta import (
    EVIDENCE_COMMUNITY,
    EVIDENCE_TOURNAMENT_PLACED,
    MetaDeck,
    Provenance,
    Tournament,
)
from riftbound.domain.meta_trends import (
    HIGH_CONFIDENCE_DECKS,
    HIGH_CONFIDENCE_EVENTS,
    MIN_DECKS_FOR_CHART_POINT,
    MIN_DECKS_FOR_MOMENTUM,
    MODERATE_CONFIDENCE_DECKS,
    TrendFilter,
    card_detail,
    card_trends,
    champion_meta,
    default_range,
    legend_meta,
    overview,
    parse_date,
    tournament_detail,
)
from riftbound.domain.meta_trends.common import _confidence, _coverage

LEGEND = "vi-piltover-enforcer"
CHAMPION = "vi-destructive"

WINDOW = TrendFilter(from_date=date(2026, 1, 1), to_date=date(2026, 3, 31), bucket="week")


def a_tournament(slug="ev-1", when="2026-02-02", players=100, published=20, fmt="Constructed"):
    return Tournament(
        tournament_id=slug, slug=slug, name=slug.title(), date=when,
        format=fmt, players=players, decks_published=published,
    )


def a_deck(
    slug="ev-1",
    when="2026-02-02",
    champion=CHAMPION,
    legend=LEGEND,
    *,
    complete=True,
    evidence=EVIDENCE_TOURNAMENT_PLACED,
    index=0,
    main_override: dict[str, int] | None = None,
) -> MetaDeck:
    """A published tournament list, complete unless asked otherwise."""
    main = {champion: 3, "brazen-buccaneer": 3, "harpoon-squad": 3, "singular-relic": 1,
            "showcase-only": 3}
    main.update({f"filler-{i:02d}": 3 for i in range(1, 10)})
    for card_id, copies in (main_override or {}).items():
        if copies <= 0:
            main.pop(card_id, None)
        else:
            main[card_id] = copies
    deck = Deck.make(
        name=f"list-{index}", legend_id=legend, champion_id=champion,
        main=main if complete else {champion: 3},
        runes={"fury-rune": 12} if complete else {},
        battlefields=["the-arena", "the-forge", "the-spire"] if complete else [],
    )
    return MetaDeck(
        deck=deck,
        provenance=Provenance(
            source="t", source_slug=f"{slug}-{index}", url="",
            evidence=evidence, tournament_slug=slug, tournament_date=when,
            placement=index + 1, field_size=100,
        ),
    )


def run(decks, tournaments, *, catalog, dimension="champion", trend_filter=WINDOW, **kw):
    return overview(
        decks=decks,
        tournaments=tournaments,
        standing_count_by_tournament={t.slug: t.players for t in tournaments},
        catalog=catalog,
        trend_filter=trend_filter,
        dimension=dimension,
        **kw,
    )


# -- dates --------------------------------------------------------------------


def test_an_unreadable_date_is_none_not_an_exception():
    """Upstream dates are somebody else's data; a bad one must not end a harvest."""
    assert parse_date("") is None
    assert parse_date("not a date") is None
    assert parse_date("2026-02-02") == date(2026, 2, 2)


def test_the_default_range_ends_at_the_latest_event(catalog):
    """Anchored to the data, not to today: a snapshot harvested last week should open
    on the window its events actually occupy."""
    events = [a_tournament(when="2026-01-05"), a_tournament(slug="b", when="2026-03-20")]
    start, end = default_range(events, days=30)
    assert end == date(2026, 3, 20)
    assert start == date(2026, 2, 19), "30 days inclusive of both ends"


def test_the_default_range_survives_having_no_events(catalog):
    """An empty snapshot is a normal state, not an error."""
    start, end = default_range([], days=30)
    assert (end - start).days == 29


# -- what counts --------------------------------------------------------------


def test_a_list_with_unresolved_cards_is_not_counted(catalog):
    """A list we could not fully read is unknown, and unknown is not zero.

    Counting an unresolved deck as evidence for its champion would be inventing data;
    counting it against them would be worse.
    """
    good = a_deck(index=0)
    bad = MetaDeck(
        deck=good.deck, provenance=good.provenance, unresolved=("VEN-999",)
    )
    result = run([good, bad], [a_tournament()], catalog=catalog)
    assert result.published_deck_count == 1


def test_community_decks_do_not_enter_tournament_trends(catalog):
    """Somebody's brew is not a tournament result and must not move a tournament line."""
    decks = [a_deck(index=0), a_deck(index=1, evidence=EVIDENCE_COMMUNITY)]
    result = run(decks, [a_tournament()], catalog=catalog)
    assert result.published_deck_count == 1


def test_a_deck_from_an_event_outside_the_window_is_dropped(catalog):
    decks = [a_deck(index=0), a_deck(slug="old", when="2025-06-01", index=1)]
    events = [a_tournament(), a_tournament(slug="old", when="2025-06-01")]
    result = run(decks, events, catalog=catalog)
    assert result.published_deck_count == 1
    assert result.tournament_count == 1


def test_a_small_event_is_excluded_when_a_floor_is_set(catalog):
    events = [a_tournament(players=100), a_tournament(slug="tiny", players=4)]
    decks = [a_deck(index=0), a_deck(slug="tiny", index=1)]
    result = run(
        decks, events, catalog=catalog,
        trend_filter=TrendFilter(WINDOW.from_date, WINDOW.to_date, min_players=16),
    )
    assert result.tournament_count == 1
    assert result.published_deck_count == 1


def test_format_filtering_is_case_insensitive(catalog):
    events = [a_tournament(fmt="Constructed")]
    result = run(
        [a_deck()], events, catalog=catalog,
        trend_filter=TrendFilter(WINDOW.from_date, WINDOW.to_date, format="constructed"),
    )
    assert result.tournament_count == 1


# -- denominators -------------------------------------------------------------


def test_share_is_measured_against_published_lists_not_attendance(catalog):
    """The central honesty claim of the whole module.

    Two published lists out of a 1,000-player event is 100% of what we can see and
    0.2% of the field. Reporting the second number as if it were the first is the
    mistake this module exists to make impossible.
    """
    events = [a_tournament(players=1000, published=2)]
    decks = [a_deck(index=0), a_deck(index=1)]
    result = run(decks, events, catalog=catalog)

    entry = result.series[0]
    assert entry.deck_count == 2
    assert entry.share == 1.0, "both published lists played it"
    # ...and the field is still reported, separately, so nobody has to guess.
    assert result.known_field_players == 1000
    assert result.published_deck_count == 2
    assert result.published_coverage == pytest.approx(0.002)


def test_the_share_denominator_is_reported_alongside_the_headline(catalog):
    """A list with no champion is dropped from champion shares -- correctly, since
    unknown is not zero -- but that makes the headline count larger than the population
    the shares divide by. Report both, or a client prints the wrong percentage.
    """
    decks = [a_deck(index=0), a_deck(index=1), a_deck(champion="", index=2)]
    result = run(decks, [a_tournament()], catalog=catalog, dimension="champion")

    assert result.published_deck_count == 3, "three lists were published"
    assert result.charted_deck_count == 2, "two of them named a champion"
    assert sum(entry.deck_count for entry in result.series) == result.charted_deck_count
    assert sum(entry.share for entry in result.series) == pytest.approx(1.0)


def test_both_populations_are_always_reported(catalog):
    """A client must be able to say "48 of 2,224" without doing its own arithmetic."""
    result = run([a_deck()], [a_tournament(players=500, published=30)], catalog=catalog)
    assert result.known_field_players == 500
    assert result.published_deck_count == 1
    assert result.standing_count == 500


def test_coverage_cannot_exceed_everyone_who_played():
    """Upstream sometimes reports more published lists than entrants.

    Believing it would print "140% of the field", which destroys trust in every other
    number on the page.
    """
    _players, published, coverage = _coverage([a_tournament(players=10, published=99)])
    assert published == 10
    assert coverage == 1.0


def test_coverage_of_an_empty_field_is_zero_not_a_crash():
    assert _coverage([a_tournament(players=0, published=0)]) == (0, 0, 0.0)


# -- movement -----------------------------------------------------------------


def test_movement_is_refused_on_a_sample_too_thin_to_support_it(catalog):
    """A number that moves for no reason is worse than no number: people act on it."""
    decks = [a_deck(when="2026-02-02", index=i) for i in range(3)]
    decks += [a_deck(slug="ev-2", when="2026-02-09", index=10 + i) for i in range(3)]
    events = [a_tournament(), a_tournament(slug="ev-2", when="2026-02-09")]
    result = run(decks, events, catalog=catalog)
    assert result.series[0].momentum is None


def test_movement_appears_once_two_intervals_can_support_it(catalog):
    """Both weeks carry a usable sample, so a direction is finally meaningful."""
    decks: list[MetaDeck] = []
    # Week one: every list plays the champion.
    for i in range(MIN_DECKS_FOR_MOMENTUM):
        decks.append(a_deck(when="2026-02-02", index=i))
    # Week two: the same size, but only half play it.
    for i in range(MIN_DECKS_FOR_MOMENTUM // 2):
        decks.append(a_deck(slug="ev-2", when="2026-02-09", index=100 + i))
    for i in range(MIN_DECKS_FOR_MOMENTUM // 2):
        decks.append(
            a_deck(slug="ev-2", when="2026-02-09", champion="other-champ", index=200 + i)
        )
    events = [
        a_tournament(published=MIN_DECKS_FOR_MOMENTUM),
        a_tournament(slug="ev-2", when="2026-02-09", published=MIN_DECKS_FOR_MOMENTUM),
    ]
    result = run(decks, events, catalog=catalog)
    entry = next(s for s in result.series if s.entity_id == CHAMPION)
    assert entry.momentum == pytest.approx(-0.5), "1.0 in week one, 0.5 in week two"


def test_the_server_says_which_intervals_are_worth_drawing(catalog):
    """The plotting threshold belongs next to the tests that pin it.

    A client re-deriving it keeps a second copy of a statistical policy in another
    language, where nothing checks it. Here the server marks each point and every
    client draws the same line.
    """
    decks = [a_deck(when="2026-02-02", index=i) for i in range(MIN_DECKS_FOR_CHART_POINT)]
    decks += [a_deck(slug="ev-2", when="2026-02-09", index=100)]
    events = [a_tournament(), a_tournament(slug="ev-2", when="2026-02-09")]
    result = run(decks, events, catalog=catalog)

    by_period = {point.period: point for point in result.series[0].points}
    thick = next(p for p in by_period.values() if p.total_decks >= MIN_DECKS_FOR_CHART_POINT)
    thin = next(p for p in by_period.values() if 0 < p.total_decks < MIN_DECKS_FOR_CHART_POINT)
    assert thick.charted is True
    assert thin.charted is False, "one list is a point on a chart nobody should read"
    assert all(not p.charted for p in by_period.values() if p.total_decks == 0)


def test_the_thin_intervals_are_still_returned(catalog):
    """Refusing to derive a direction is not a reason to hide the data.

    The points stay in the response so a client can show the line and let a reader see
    for themselves how thin it is.
    """
    decks = [a_deck(when="2026-02-02", index=i) for i in range(3)]
    result = run(decks, [a_tournament()], catalog=catalog)
    entry = result.series[0]
    assert entry.momentum is None
    assert any(point.decks == 3 for point in entry.points)


# -- confidence ---------------------------------------------------------------


def test_confidence_needs_lists_events_and_coverage_together():
    """Any one of the three being strong is not enough; a wide sample of one event is
    still one event."""
    assert _confidence(HIGH_CONFIDENCE_DECKS, HIGH_CONFIDENCE_EVENTS, 0.2) == "high"
    # A hundred lists from a single event is still a single metagame, and the label
    # says so rather than borrowing confidence from the deck count alone.
    assert _confidence(HIGH_CONFIDENCE_DECKS, 1, 0.2) == "limited", "one event"
    assert _confidence(HIGH_CONFIDENCE_DECKS, HIGH_CONFIDENCE_EVENTS, 0.01) == "moderate"
    assert _confidence(1, 1, 0.9) == "limited"


def test_confidence_degrades_rather_than_disappearing():
    """Every sample gets a label. Silence would read as "fine"."""
    assert _confidence(MODERATE_CONFIDENCE_DECKS, 3, 0.0) == "moderate"
    assert _confidence(0, 0, 0.0) == "limited"


# -- shape --------------------------------------------------------------------


def test_series_are_ranked_by_evidence(catalog):
    decks = [a_deck(index=i) for i in range(3)]
    decks += [a_deck(champion="other-champ", index=10)]
    result = run(decks, [a_tournament()], catalog=catalog)
    assert result.series[0].entity_id == CHAMPION
    assert result.series[0].deck_count == 3


def test_the_limit_is_honoured(catalog):
    decks = [a_deck(champion=f"champ-{i}", index=i) for i in range(8)]
    result = run(decks, [a_tournament()], catalog=catalog, limit=3)
    assert len(result.series) == 3


def test_every_period_in_the_window_gets_a_point(catalog):
    """A gap in the data is a visible gap in the line, not a missing x-axis step."""
    result = run([a_deck()], [a_tournament()], catalog=catalog)
    periods = [point.period for point in result.series[0].points]
    assert len(periods) == len(set(periods)), "no duplicated intervals"
    assert len(periods) > 1
    assert any(point.decks == 0 for point in result.series[0].points)


def test_monthly_buckets_are_coarser_than_weekly(catalog):
    decks = [a_deck(when="2026-02-02", index=0), a_deck(slug="b", when="2026-02-20", index=1)]
    events = [a_tournament(), a_tournament(slug="b", when="2026-02-20")]
    weekly = run(decks, events, catalog=catalog)
    monthly = run(
        decks, events, catalog=catalog,
        trend_filter=TrendFilter(WINDOW.from_date, WINDOW.to_date, bucket="month"),
    )
    assert len(monthly.series[0].points) < len(weekly.series[0].points)


def test_an_empty_window_is_answerable(catalog):
    """No events in range is a normal question with a normal answer."""
    result = run([], [], catalog=catalog)
    assert result.series == ()
    assert result.published_deck_count == 0
    assert result.published_coverage == 0.0


def test_legend_and_champion_dimensions_group_differently(catalog):
    """Two champions under one legend is one legend line and two champion lines."""
    decks = [a_deck(index=0), a_deck(champion="other-champ", index=1)]
    by_champion = run(decks, [a_tournament()], catalog=catalog, dimension="champion")
    by_legend = run(decks, [a_tournament()], catalog=catalog, dimension="legend")
    assert len(by_champion.series) == 2
    assert len(by_legend.series) == 1
    assert by_legend.series[0].deck_count == 2


def test_a_deck_with_no_champion_is_left_out_of_champion_trends(catalog):
    """Unknown is not an entity. v2 grew a phantom "" archetype exactly this way."""
    decks = [a_deck(index=0), a_deck(champion="", index=1)]
    result = run(decks, [a_tournament()], catalog=catalog, dimension="champion")
    assert [s.entity_id for s in result.series] == [CHAMPION]


# -- tournament detail --------------------------------------------------------


def test_a_tournaments_champion_shares_sum_to_one(catalog):
    """The denominator bug, caught on real data and pinned here.

    Dividing by every complete list rather than by the lists that named a champion
    shrinks every share toward zero. At one real event the distribution summed to 0.14,
    so a page reading "14% played Master Yi" was describing a field where every list
    that named a champion played him.
    """
    decks = [
        a_deck(index=0),
        a_deck(index=1),
        a_deck(champion="", index=2),          # complete, but no champion recorded
    ]
    detail = tournament_detail(
        slug="ev-1", tournaments=[a_tournament()], decks=decks, catalog=catalog
    )
    assert detail is not None
    assert detail.known_deck_count == 3, "three complete lists were published"
    assert detail.charted_deck_count == 2, "two of them named a champion"
    assert sum(entity.share for entity in detail.champions) == pytest.approx(1.0)
    assert detail.champions[0].share == 1.0


def test_a_tournament_with_no_champions_at_all_does_not_divide_by_zero(catalog):
    detail = tournament_detail(
        slug="ev-1",
        tournaments=[a_tournament()],
        decks=[a_deck(champion="", index=0)],
        catalog=catalog,
    )
    assert detail is not None
    assert detail.champions == ()
    assert detail.charted_deck_count == 0


def test_an_unknown_tournament_is_none_not_an_empty_page(catalog):
    assert tournament_detail(
        slug="nope", tournaments=[a_tournament()], decks=[], catalog=catalog
    ) is None


def test_tournament_coverage_cannot_exceed_the_field(catalog):
    detail = tournament_detail(
        slug="ev-1",
        tournaments=[a_tournament(players=10, published=99)],
        decks=[a_deck(index=0)],
        catalog=catalog,
    )
    assert detail is not None
    assert detail.published_coverage == 1.0


def test_placed_decks_come_before_unplaced_ones(catalog):
    """An unrecorded placement sorts last rather than winning the event."""
    unplaced = a_deck(index=0)
    unplaced = MetaDeck(
        deck=unplaced.deck,
        provenance=Provenance(
            source="t", source_slug="x", url="", evidence=EVIDENCE_TOURNAMENT_PLACED,
            tournament_slug="ev-1", tournament_date="2026-02-02",
            placement=0, field_size=100,
        ),
    )
    detail = tournament_detail(
        slug="ev-1",
        tournaments=[a_tournament()],
        decks=[unplaced, a_deck(index=4)],
        catalog=catalog,
    )
    assert detail is not None
    assert detail.decks[0].placement == 5
    assert detail.decks[-1].placement == 0


# -- champion and legend guides ----------------------------------------------


def test_a_champion_with_no_tournament_data_is_none(catalog):
    """Better an honest absence than a page of zeroes that looks like a result."""
    assert champion_meta(
        champion_id="never-played",
        decks=[a_deck()],
        tournaments=[a_tournament()],
        standing_count_by_tournament={},
        catalog=catalog,
        trend_filter=WINDOW,
    ) is None


def test_a_champion_guide_counts_finishes_it_actually_made(catalog):
    decks = [a_deck(index=0), a_deck(index=8), a_deck(index=20)]  # places 1, 9, 21
    result = champion_meta(
        champion_id=CHAMPION,
        decks=decks,
        tournaments=[a_tournament()],
        standing_count_by_tournament={},
        catalog=catalog,
        trend_filter=WINDOW,
    )
    assert result is not None
    assert result.top_eight == 1
    assert result.top_sixteen == 2
    assert result.best_placement == 1
    assert result.best_field_size == 100, "a finish means nothing without the field size"


def test_a_legend_guide_reports_the_champions_played_under_it(catalog):
    decks = [a_deck(index=0), a_deck(champion="other-champ", index=1)]
    result = legend_meta(
        legend_id=LEGEND,
        decks=decks,
        tournaments=[a_tournament()],
        standing_count_by_tournament={},
        catalog=catalog,
        trend_filter=WINDOW,
    )
    assert result is not None
    assert {entry.entity_id for entry in result.champions} == {CHAMPION, "other-champ"}
    assert result.overview.deck_count == 2


# -- cards --------------------------------------------------------------------


def card_run(decks, tournaments, *, catalog, **kw):
    return card_trends(
        decks=decks, tournaments=tournaments, catalog=catalog, trend_filter=WINDOW, **kw
    )


def test_adoption_is_not_a_share_and_does_not_pretend_to_be(catalog):
    """The distinction the card types exist for.

    A champion's share is a partition -- one per list, summing to 1. A card's adoption
    is not: a list plays forty of them. Naming both "share" would invite dividing one by
    the other, which is the arithmetic this module exists to prevent.
    """
    result = card_run([a_deck(index=0)], [a_tournament()], catalog=catalog)
    assert result.charted_deck_count == 1
    total = sum(entry.adoption for entry in result.series)
    assert total > 1.0, "one list adopts many cards; this is not a partition"
    assert all(entry.adoption <= 1.0 for entry in result.series)
    assert not hasattr(result.series[0], "share")


def test_a_card_in_every_list_has_full_adoption(catalog):
    decks = [a_deck(index=i) for i in range(4)]
    result = card_run(decks, [a_tournament()], catalog=catalog)
    entry = next(e for e in result.series if e.card_id == "brazen-buccaneer")
    assert entry.decks == 4
    assert entry.adoption == pytest.approx(1.0)


def test_runes_and_battlefields_are_tracked_too(catalog):
    """They are cards people have to own, and the wizard asks about them."""
    result = card_run([a_deck(index=0)], [a_tournament()], catalog=catalog)
    tracked = {entry.card_id for entry in result.series}
    assert "fury-rune" in tracked
    assert "the-arena" in tracked


def test_average_copies_reflects_what_the_field_runs(catalog):
    result = card_run([a_deck(index=0)], [a_tournament()], catalog=catalog)
    by_id = {entry.card_id: entry for entry in result.series}
    assert by_id["brazen-buccaneer"].average_copies == pytest.approx(3.0)
    assert by_id["singular-relic"].average_copies == pytest.approx(1.0)
    assert by_id["fury-rune"].average_copies == pytest.approx(12.0)


def test_card_movement_obeys_the_same_restraint_as_everything_else(catalog):
    """A thin interval cannot produce a direction here either."""
    decks = [a_deck(index=i) for i in range(3)]
    result = card_run(decks, [a_tournament()], catalog=catalog)
    assert all(entry.momentum is None for entry in result.series)


def test_cards_can_be_filtered_to_one_type(catalog):
    result = card_run([a_deck(index=0)], [a_tournament()], catalog=catalog, card_type="Rune")
    assert result.series
    assert {entry.card_type for entry in result.series} == {"Rune"}


# -- one card -----------------------------------------------------------------


def test_a_card_nobody_played_has_no_page(catalog):
    """An honest absence beats a page of zeroes that reads like a result."""
    assert card_detail(
        card_id="calm-intruder", decks=[a_deck(index=0)], tournaments=[a_tournament()],
        catalog=catalog, trend_filter=WINDOW,
    ) is None


def test_the_copies_split_shows_what_the_average_hides(catalog):
    """A card played as a one-of is a different card to one played as a three-of."""
    ones = [a_deck(index=i, main_override={"harpoon-squad": 1}) for i in range(3)]
    threes = [a_deck(index=10 + i) for i in range(3)]
    detail = card_detail(
        card_id="harpoon-squad", decks=ones + threes, tournaments=[a_tournament()],
        catalog=catalog, trend_filter=WINDOW,
    )
    assert detail is not None
    assert dict(detail.copies_split) == {1: 3, 3: 3}
    assert detail.trend.average_copies == pytest.approx(2.0), "which nobody actually plays"


def test_partners_are_ranked_by_lift_not_by_ubiquity(catalog):
    """Otherwise the most-played card in the format tops every card's partner list and
    tells nobody anything."""
    together = [a_deck(index=i) for i in range(6)]
    apart = [
        a_deck(index=20 + i, main_override={"harpoon-squad": 0, "calm-intruder": 0})
        for i in range(6)
    ]
    detail = card_detail(
        card_id="harpoon-squad", decks=together + apart, tournaments=[a_tournament()],
        catalog=catalog, trend_filter=WINDOW,
    )
    assert detail is not None
    assert detail.partners
    assert all(partner.lift >= 1.0 for partner in detail.partners[:3])


def test_a_cards_homes_add_up_to_where_it_is_played(catalog):
    detail = card_detail(
        card_id="brazen-buccaneer", decks=[a_deck(index=i) for i in range(3)],
        tournaments=[a_tournament()], catalog=catalog, trend_filter=WINDOW,
    )
    assert detail is not None
    assert sum(home.decks for home in detail.legends) == detail.trend.decks
    assert detail.legends[0].share_of_card == pytest.approx(1.0)


# -- the archive --------------------------------------------------------------


def test_the_archive_span_is_reported_alongside_the_window(catalog):
    """So a page can say there is more behind the default range."""
    events = [
        a_tournament(slug="old", when="2026-01-05"),
        a_tournament(slug="new", when="2026-02-02"),
    ]
    decks = [a_deck(slug="new", index=0)]
    result = run(
        decks, events, catalog=catalog,
        trend_filter=TrendFilter(date(2026, 1, 20), date(2026, 3, 31)),
    )
    assert result.tournament_count == 1, "the window holds one"
    assert result.archive_tournament_count == 2, "the archive holds two"
    assert result.archive_from == "2026-01-05"


def test_the_archive_count_is_comparable_with_the_window_count(catalog):
    """Both sides of "showing X of Y" must answer the same question.

    Counting every event regardless of size against a view filtered to 16+ players
    produced "showing 124 of 333 -- the whole archive", which is two different questions
    sharing a sentence. Every filter except the dates applies to both.
    """
    events = [
        a_tournament(slug="big", when="2026-02-02", players=100),
        a_tournament(slug="tiny-old", when="2026-01-05", players=4),
        a_tournament(slug="big-old", when="2026-01-05", players=100),
    ]
    result = run(
        [a_deck(slug="big", index=0)], events, catalog=catalog,
        trend_filter=TrendFilter(date(2026, 1, 20), date(2026, 3, 31), min_players=16),
    )
    assert result.tournament_count == 1
    assert result.archive_tournament_count == 2, "the tiny event is excluded from both"


def test_showing_everything_means_the_two_counts_agree(catalog):
    """The "whole archive" case has to actually look like it."""
    events = [a_tournament(slug="a", when="2026-01-05"), a_tournament(slug="b", when="2026-02-02")]
    result = run(
        [a_deck(slug="a", index=0)], events, catalog=catalog,
        trend_filter=TrendFilter(date(2026, 1, 1), date(2026, 3, 31)),
    )
    assert result.tournament_count == result.archive_tournament_count == 2


def test_the_card_wall_reports_the_same_archive(catalog):
    result = card_run([a_deck(index=0)], [a_tournament()], catalog=catalog)
    assert result.archive_tournament_count == 1
    assert result.archive_from == result.archive_to == "2026-02-02"


def test_an_empty_archive_reports_nothing_rather_than_a_date(catalog):
    result = run([], [], catalog=catalog)
    assert result.archive_from == ""
    assert result.archive_tournament_count == 0


# -- ranking, and the field this window cannot see ----------------------------
#
# The scoring itself is pinned in test_ranking. These cover the join: that `overview`
# finds the entities the archive knows and this window does not, and that asking for
# them changes nothing for a caller who did not.


def test_every_series_row_arrives_ranked_and_in_rank_order(catalog):
    tournaments = [a_tournament("ev-1", "2026-02-02"), a_tournament("ev-2", "2026-02-09")]
    decks = [
        a_deck("ev-1", "2026-02-02", champion=CHAMPION, index=0),
        a_deck("ev-1", "2026-02-02", champion=CHAMPION, index=1),
        a_deck("ev-2", "2026-02-09", champion="harpoon-squad", index=2),
    ]
    result = run(decks, tournaments, catalog=catalog)
    assert all(row.rank is not None for row in result.series)
    positions = [row.rank.position for row in result.series]
    assert positions == sorted(positions)
    assert result.series[0].rank.position == 1
    # The leader sets the top of the scale, so it takes every presence point going.
    assert result.series[0].rank.score > result.series[-1].rank.score


def test_dormant_entities_are_absent_unless_asked_for(catalog):
    """The response shape only changes for a caller that opted in."""
    tournaments = [a_tournament("old", "2026-01-05"), a_tournament("new", "2026-03-09")]
    decks = [
        a_deck("old", "2026-01-05", champion="harpoon-squad", index=0),
        a_deck("new", "2026-03-09", champion=CHAMPION, index=1),
    ]
    window = TrendFilter(from_date=date(2026, 3, 1), to_date=date(2026, 3, 31), bucket="week")

    plain = run(decks, tournaments, catalog=catalog, trend_filter=window)
    assert [row.entity_id for row in plain.series] == [CHAMPION]

    with_dormant = run(
        decks, tournaments, catalog=catalog, trend_filter=window, include_dormant=True
    )
    assert [row.entity_id for row in with_dormant.series] == [CHAMPION, "harpoon-squad"]


def test_a_dormant_entity_scores_zero_and_says_when_it_was_last_seen(catalog):
    tournaments = [a_tournament("old", "2026-01-05"), a_tournament("new", "2026-03-09")]
    decks = [
        a_deck("old", "2026-01-05", champion="harpoon-squad", index=0),
        a_deck("new", "2026-03-09", champion=CHAMPION, index=1),
    ]
    window = TrendFilter(from_date=date(2026, 3, 1), to_date=date(2026, 3, 31), bucket="week")
    result = run(decks, tournaments, catalog=catalog, trend_filter=window, include_dormant=True)

    dormant = next(row for row in result.series if row.entity_id == "harpoon-squad")
    assert dormant.rank.ranked is False
    assert dormant.rank.score == 0.0
    assert dormant.deck_count == 0
    assert dormant.share == 0.0
    # It was played, just not here — and the row says so instead of showing a bare zero.
    assert dormant.rank.last_seen == "2026-01-05"
    assert dormant.rank.prior_share > 0


def test_a_window_covering_the_whole_archive_has_nothing_dormant(catalog):
    """Nothing can be absent from a window that contains everything."""
    tournaments = [a_tournament("ev-1", "2026-02-02")]
    decks = [a_deck("ev-1", "2026-02-02", index=0)]
    result = run(decks, tournaments, catalog=catalog, include_dormant=True)
    assert all(row.rank.ranked for row in result.series)


def test_dormant_entities_do_not_dilute_the_shares(catalog):
    """They join the ranking at zero; they must not join the denominator."""
    tournaments = [a_tournament("old", "2026-01-05"), a_tournament("new", "2026-03-09")]
    decks = [
        a_deck("old", "2026-01-05", champion="harpoon-squad", index=0),
        a_deck("new", "2026-03-09", champion=CHAMPION, index=1),
    ]
    window = TrendFilter(from_date=date(2026, 3, 1), to_date=date(2026, 3, 31), bucket="week")
    result = run(decks, tournaments, catalog=catalog, trend_filter=window, include_dormant=True)
    assert sum(row.share for row in result.series) == pytest.approx(1.0)
    assert result.charted_deck_count == 1
