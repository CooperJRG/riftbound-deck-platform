"""Win rate, and the claims it is allowed to make.

The arithmetic here is easy and would survive any refactor. What these tests pin is
*restraint* — the properties a well-meaning change quietly breaks:

* a rate is never shown on a sample that cannot support one, and the refusal says why;
* draws are neither wins nor losses, and the two denominators stay separate;
* the interval is a real interval, inside [0, 1], narrowing with evidence;
* an entity with no records is absent, never a 0% win rate;
* the era is respected, so a ban-era boundary is not averaged across;
* presence and performance stay two numbers and are never blended into one;
* the publication bias is carried in the response, so the caveat cannot be dropped.

The last one matters most. v2's failure was not that a number was wrong; it was that
the number that would have embarrassed it was never in front of anyone.
"""

from __future__ import annotations

from datetime import date

import pytest

from conftest import make_card
from riftbound.domain.cards import build_catalog
from riftbound.domain.deck import Deck
from riftbound.domain.eras import Eras, eras_from
from riftbound.domain.meta import (
    EVIDENCE_TOURNAMENT_PLACED,
    MetaDeck,
    Provenance,
    Standing,
    Tournament,
    parse_record,
)
from riftbound.domain.meta_trends import overview
from riftbound.domain.meta_trends.common import TrendFilter
from riftbound.domain.meta_trends.performance import (
    MAX_PILOT_SHARE,
    MIN_EVENTS,
    MIN_MATCHES,
    WITHHELD_EVENTS,
    WITHHELD_MATCHES,
    WITHHELD_PILOT,
    performance,
    signal_to_noise,
    wilson,
)

LEGEND = "vi-piltover-enforcer"
CHAMPION = "vi-destructive"
WINDOW = TrendFilter(from_date=date(2026, 4, 1), to_date=date(2026, 8, 31), bucket="week")

# Just enough catalogue to name an archetype. Performance aggregation never reads a
# card's stats -- only its display name -- so anything larger would be scenery.
CATALOG = build_catalog(
    [
        make_card(LEGEND, "Vi - Piltover Enforcer", card_type="Legend",
                  champion_tags=("Vi",), cost=None, might=None),
        make_card(CHAMPION, "Vi - Destructive", super_type="Champion", champion_tags=("Vi",)),
        make_card("brazen-buccaneer", "Brazen Buccaneer"),
        make_card("fury-rune", "Fury Rune", card_type="Rune", cost=None, might=None),
        make_card("the-arena", "The Arena", card_type="Battlefield", cost=None, might=None),
        make_card("the-forge", "The Forge", card_type="Battlefield", cost=None, might=None),
        make_card("the-spire", "The Spire", card_type="Battlefield", cost=None, might=None),
    ]
)

ERAS = eras_from(
    {
        "periods": [
            {"id": "launch", "name": "Launch", "to": "2026-03-28"},
            {"id": "post-ban", "name": "Post ban", "from": "2026-03-29"},
        ]
    }
)


def a_tournament(slug: str, when: str = "2026-05-05", players: int = 64) -> Tournament:
    return Tournament(
        tournament_id=slug, slug=slug, name=slug.title(), date=when,
        format="Constructed", players=players, decks_published=players,
    )


def a_deck(deck_id: str, slug: str, when: str = "2026-05-05", champion: str = CHAMPION):
    return MetaDeck(
        deck=Deck.make(
            name=deck_id, format="constructed", legend_id=LEGEND, champion_id=champion,
            main={"brazen-buccaneer": 3}, runes={"fury-rune": 12},
            battlefields=["the-arena", "the-forge", "the-spire"], sideboard={},
        ),
        provenance=Provenance(
            source="topdeck", source_slug=deck_id, url="",
            published_at=when, evidence=EVIDENCE_TOURNAMENT_PLACED,
            tournament_slug=slug, tournament_name=slug, tournament_date=when,
            placement=1, field_size=64,
        ),
    )


def a_standing(deck_id, slug, wins, losses, draws=0, player="p"):
    return Standing(
        tournament_slug=slug, place=1, player_name=player,
        deck_slug=deck_id, record=f"{wins}-{losses}", wins=wins, losses=losses, draws=draws,
    )


def a_field(*, events: int, per_event: int, wins: int, losses: int, draws: int = 0,
            champion: str = CHAMPION, when: str = "2026-05-05", pilot=None):
    """A field big enough to clear the thresholds, spread over distinct events."""
    tournaments, decks, standings = [], [], []
    # The date is part of the slug so two eras of the same archetype do not collide on
    # tournament ids -- which would silently merge the populations the era test exists
    # to keep apart.
    for e in range(events):
        slug = f"ev-{champion or 'none'}-{when}-{e}"
        tournaments.append(a_tournament(slug, when))
        for i in range(per_event):
            deck_id = f"{slug}::{i}"
            decks.append(a_deck(deck_id, slug, when, champion))
            standings.append(
                a_standing(
                    deck_id, slug, wins, losses, draws,
                    player=pilot(e, i) if pilot else f"player-{e}-{i}",
                )
            )
    return tournaments, decks, standings


def run(tournaments, decks, standings, *, era_id="post-ban", window=WINDOW):
    return performance(
        decks=decks, tournaments=tournaments, standings=standings,
        catalog=CATALOG, trend_filter=window, eras=ERAS, era_id=era_id,
        dimension="archetype",
    )


# -- the interval -------------------------------------------------------------


def test_wilson_stays_inside_the_unit_interval_at_tiny_samples():
    """The reason for Wilson over the normal approximation, in one assertion.

    ``p +/- z*sqrt(p(1-p)/n)`` on a 1-0 record returns a high bound above 1.0, and an
    interval claiming a deck wins 130% of its games discredits every other number on
    the page.
    """
    for wins, decisive in ((1, 1), (0, 1), (3, 3), (0, 5), (17, 17)):
        _rate, low, high = wilson(wins, decisive)
        assert 0.0 <= low <= high <= 1.0


def test_the_interval_narrows_as_evidence_arrives():
    _r, low_small, high_small = wilson(30, 50)
    _r, low_big, high_big = wilson(300, 500)
    assert (high_big - low_big) < (high_small - low_small)


def test_no_matches_is_not_a_zero_percent_win_rate():
    rate, low, high = wilson(0, 0)
    assert (rate, low, high) == (0.0, 0.0, 1.0)


# -- denominators -------------------------------------------------------------


def test_draws_count_as_matches_but_not_as_losses():
    """A draw is evidence a game happened and no evidence about who is better."""
    tournaments, decks, standings = a_field(
        events=MIN_EVENTS, per_event=20, wins=1, losses=1, draws=1
    )
    row = run(tournaments, decks, standings).get(f"{LEGEND}::{CHAMPION}")
    assert row is not None
    assert row.matches == row.decisive + row.draws
    assert row.win_rate == pytest.approx(0.5)


def test_a_standing_with_no_record_is_dropped_not_counted_as_a_loss():
    tournaments, decks, standings = a_field(
        events=MIN_EVENTS, per_event=20, wins=3, losses=0
    )
    blank = [
        Standing(tournament_slug=s.tournament_slug, place=9, player_name="ghost",
                 deck_slug=s.deck_slug, record="")
        for s in standings[:10]
    ]
    with_blanks = run(tournaments, decks, standings + blank).get(f"{LEGEND}::{CHAMPION}")
    without = run(tournaments, decks, standings).get(f"{LEGEND}::{CHAMPION}")
    assert with_blanks.decisive == without.decisive
    assert with_blanks.win_rate == without.win_rate


def test_an_entity_with_no_records_at_all_is_absent_rather_than_zero():
    tournaments = [a_tournament("ev-1")]
    decks = [a_deck("ev-1::0", "ev-1")]
    table = run(tournaments, decks, [])
    assert table.rows == {}
    assert table.basis.entities_measured == 0


# -- refusal ------------------------------------------------------------------


def test_a_thin_sample_is_withheld_and_says_so():
    tournaments, decks, standings = a_field(events=MIN_EVENTS, per_event=2, wins=3, losses=0)
    row = run(tournaments, decks, standings).get(f"{LEGEND}::{CHAMPION}")
    assert row.decisive < MIN_MATCHES
    assert not row.shown
    assert row.withheld == WITHHELD_MATCHES
    assert str(MIN_MATCHES) in row.explain_withheld()


def test_a_big_sample_from_too_few_events_is_withheld():
    """Ten thousand matches at two tournaments describe two tournaments."""
    tournaments, decks, standings = a_field(events=2, per_event=200, wins=3, losses=1)
    row = run(tournaments, decks, standings).get(f"{LEGEND}::{CHAMPION}")
    assert row.decisive > MIN_MATCHES
    assert not row.shown
    assert row.withheld == WITHHELD_EVENTS


def test_one_pilot_dominating_the_sample_is_withheld_as_a_player_rating():
    tournaments, decks, standings = a_field(
        events=MIN_EVENTS, per_event=20, wins=3, losses=1,
        # One player takes every seat: a deck rating that is really a person.
        pilot=lambda event, index: "the-same-person",
    )
    row = run(tournaments, decks, standings).get(f"{LEGEND}::{CHAMPION}")
    assert row.top_pilot_share > MAX_PILOT_SHARE
    assert not row.shown
    assert row.withheld == WITHHELD_PILOT
    assert "pilot" in row.explain_withheld() or "player" in row.explain_withheld()


def test_a_withheld_row_still_carries_its_counts():
    """"Not enough yet" needs a number, or a player cannot see it filling up."""
    tournaments, decks, standings = a_field(events=MIN_EVENTS, per_event=2, wins=3, losses=0)
    row = run(tournaments, decks, standings).get(f"{LEGEND}::{CHAMPION}")
    assert row.matches > 0
    assert row.decks_with_records > 0
    assert str(row.decisive) in row.explain_withheld()


def test_only_a_fully_separated_interval_claims_a_winning_deck():
    tournaments, decks, standings = a_field(events=MIN_EVENTS, per_event=30, wins=1, losses=1)
    row = run(tournaments, decks, standings).get(f"{LEGEND}::{CHAMPION}")
    assert row.shown
    assert row.win_rate == pytest.approx(0.5)
    assert not row.separated  # an even deck must never read as a winning one


# -- eras ---------------------------------------------------------------------


def test_an_era_does_not_average_across_a_ban():
    """The whole reason eras exist: two formats are not one population."""
    old = a_field(events=MIN_EVENTS, per_event=20, wins=4, losses=0, when="2026-02-02")
    new = a_field(events=MIN_EVENTS, per_event=20, wins=0, losses=4, when="2026-05-05")
    tournaments = old[0] + new[0]
    decks = old[1] + new[1]
    standings = old[2] + new[2]
    window = TrendFilter(from_date=date(2026, 1, 1), to_date=date(2026, 8, 31))

    current = run(tournaments, decks, standings, era_id="post-ban", window=window)
    legacy = run(tournaments, decks, standings, era_id="launch", window=window)
    everything = run(tournaments, decks, standings, era_id="all", window=window)

    key = f"{LEGEND}::{CHAMPION}"
    assert current.get(key).win_rate == pytest.approx(0.0)
    assert legacy.get(key).win_rate == pytest.approx(1.0)
    assert everything.get(key).win_rate == pytest.approx(0.5)
    assert current.basis.era_id == "post-ban"


def test_the_basis_says_which_era_and_whether_the_boundary_is_cited():
    tournaments, decks, standings = a_field(events=MIN_EVENTS, per_event=20, wins=3, losses=1)
    basis = run(tournaments, decks, standings).basis
    assert basis.era_name == "Post ban"
    assert basis.era_from == "2026-03-29"
    # Derived from the archive, not read off an announcement. It must keep saying so.
    assert basis.era_cited is False


def test_an_unknown_era_is_never_folded_into_a_real_one():
    assert ERAS.for_date("2026-03-28").era_id == "launch"
    assert ERAS.for_date("2026-03-29").era_id == "post-ban"
    assert ERAS.for_date("not-a-date").era_id == "unknown"
    assert Eras(periods=()).current.era_id == "unknown"


# -- publication bias ---------------------------------------------------------


def test_the_publication_gap_is_measured_and_returned():
    """The caveat is data, not a footnote somebody remembers to render."""
    tournaments, decks, standings = a_field(events=MIN_EVENTS, per_event=20, wins=3, losses=1)
    # Players from the same events whose lists were never published, and who did worse.
    unpublished = [
        Standing(tournament_slug=t.slug, place=99, player_name=f"dropped-{i}",
                 deck_slug=f"{t.slug}::unpublished-{i}", record="0-3",
                 wins=0, losses=3)
        for i, t in enumerate(tournaments)
    ]
    basis = run(tournaments, decks, standings + unpublished).basis
    assert basis.published_win_rate == pytest.approx(0.75)
    assert basis.unpublished_win_rate == pytest.approx(0.0)
    assert basis.publication_gap > 0
    assert basis.unpublished_standings == len(tournaments)
    assert "published lists" in basis.caveat


def test_the_basis_counts_what_it_could_not_rank():
    thin = a_field(events=MIN_EVENTS, per_event=2, wins=3, losses=0, champion=CHAMPION)
    thick = a_field(events=MIN_EVENTS, per_event=30, wins=3, losses=1, champion="")
    basis = run(
        thin[0] + thick[0], thin[1] + thick[1], thin[2] + thick[2]
    ).basis
    assert basis.entities_measured == basis.entities_shown + basis.entities_withheld
    assert basis.entities_withheld >= 1


# -- ranking ------------------------------------------------------------------


def test_ranking_uses_the_lower_bound_so_a_lucky_sample_cannot_win():
    """A 4-1 archetype must not outrank a 340-260 one."""
    lucky = a_field(events=MIN_EVENTS, per_event=30, wins=4, losses=3, champion=CHAMPION)
    solid = a_field(events=MIN_EVENTS, per_event=90, wins=4, losses=3, champion="")
    table = run(lucky[0] + solid[0], lucky[1] + solid[1], lucky[2] + solid[2])
    ranked = table.ranked()
    assert len(ranked) == 2
    # Same point estimate; the better-evidenced one ranks first.
    assert ranked[0].win_rate == pytest.approx(ranked[1].win_rate)
    assert ranked[0].decisive > ranked[1].decisive
    assert ranked[0].interval_low > ranked[1].interval_low


def test_ranked_never_includes_a_withheld_row():
    thin = a_field(events=MIN_EVENTS, per_event=2, wins=3, losses=0)
    assert run(*thin).ranked() == ()


def test_signal_to_noise_falls_towards_one_when_entities_do_not_differ():
    """The kill switch: identical entities must not look like a ranking."""
    same = []
    for champion in ("", CHAMPION):
        same.append(a_field(events=MIN_EVENTS, per_event=40, wins=1, losses=1, champion=champion))
    table = run(
        same[0][0] + same[1][0], same[0][1] + same[1][1], same[0][2] + same[1][2]
    )
    assert signal_to_noise(table) == pytest.approx(0.0, abs=0.01)


# -- integration with the trend overview --------------------------------------


def test_presence_and_performance_stay_two_numbers(catalog):
    tournaments, decks, standings = a_field(events=MIN_EVENTS, per_event=20, wins=3, losses=1)
    result = overview(
        decks=decks, tournaments=tournaments,
        standing_count_by_tournament={t.slug: t.players for t in tournaments},
        catalog=catalog, trend_filter=WINDOW, dimension="archetype",
        standings=standings, eras=ERAS, era_id="post-ban",
    )
    series = result.series[0]
    assert series.share == pytest.approx(1.0)          # presence
    assert series.performance is not None
    assert series.performance.win_rate == pytest.approx(0.75)   # performance
    assert result.performance_basis is not None


def test_an_overview_without_standings_reports_not_measured_rather_than_zero(catalog):
    """Every existing caller passes no standings. None must mean unknown, not 0%."""
    tournaments, decks, _standings = a_field(events=MIN_EVENTS, per_event=20, wins=3, losses=1)
    result = overview(
        decks=decks, tournaments=tournaments,
        standing_count_by_tournament={t.slug: t.players for t in tournaments},
        catalog=catalog, trend_filter=WINDOW, dimension="archetype",
    )
    assert result.series[0].performance is None
    assert result.performance_basis is None


# -- the legacy record string -------------------------------------------------


def test_a_snapshot_written_before_typed_counts_still_yields_its_records():
    """The backfill that means this feature needs no re-harvest."""
    legacy = Standing(tournament_slug="ev", place=1, player_name="p", record="5-2-1")
    assert legacy.match_record == (5, 2, 1)
    assert legacy.decisive == 7
    assert legacy.matches == 8


def test_typed_counts_win_over_the_display_string():
    both = Standing(
        tournament_slug="ev", place=1, player_name="p",
        record="9-9", wins=3, losses=1, draws=0,
    )
    assert both.match_record == (3, 1, 0)


@pytest.mark.parametrize("value", ["", "  ", "x-y", "3", "3-", "-1-2", "3-1-1-1", None])
def test_an_unreadable_record_is_no_record_rather_than_an_exception(value):
    assert parse_record(value) == (0, 0, 0)
    assert not Standing(tournament_slug="ev", place=1, player_name="p", record=value or "").has_record
