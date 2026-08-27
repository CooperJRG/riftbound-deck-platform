"""The tier list's ordering, and the claims a rating is allowed to make.

This logic spent its life in `web/src/features/explore.ts` with no tests at all — the
only piece of ranking policy outside the server. These are the properties that were
never guarded:

* the scale is 0-100 and both ends mean something;
* the parts add up to the whole, so a card explaining itself cannot be lying;
* an entity with no lists scores 0, keeps a position, and is never confused with one
  that was measured and did badly;
* dormant entities are ordered by prior evidence rather than by dictionary order;
* the order is stable across runs, so a rebuild of one snapshot produces one wall.
"""

from __future__ import annotations

from itertools import pairwise

import pytest

from riftbound.domain.meta_trends.ranking import (
    GRADE_CURVE,
    MOMENTUM_CLAMP,
    MOMENTUM_UNKNOWN,
    TIER_LAST,
    TIER_ORDER,
    W_BREADTH,
    W_MOMENTUM,
    W_PRESENCE,
    Candidate,
    grade,
    momentum_points,
    rank_entities,
    tier_for,
)


def played(entity_id, name=None, *, share=0.05, events=10, momentum=0.0):
    return Candidate(
        entity_id=entity_id, name=name or entity_id.title(),
        share=share, event_count=events, momentum=momentum,
    )


def dormant(entity_id, name=None, *, prior_share=0.0, prior_momentum=None, last_seen=""):
    return Candidate(
        entity_id=entity_id, name=name or entity_id.title(),
        share=0.0, event_count=0, momentum=None, ranked=False,
        prior_share=prior_share, prior_momentum=prior_momentum, last_seen=last_seen,
    )


# -- the scale ----------------------------------------------------------------


def test_the_weights_sum_to_one_so_the_total_reads_as_a_percentage():
    """The property that makes 0-100 meaningful rather than an arbitrary index."""
    assert pytest.approx(1.0) == W_PRESENCE + W_BREADTH + W_MOMENTUM


def test_leading_every_component_scores_one_hundred():
    ranks = rank_entities([
        played("best", share=0.30, events=80, momentum=MOMENTUM_CLAMP),
        played("rest", share=0.10, events=20, momentum=0.0),
    ])
    assert ranks["best"].score == pytest.approx(100.0)


def test_the_parts_add_up_to_the_whole():
    """A card shows the breakdown; if it does not reconcile, the card is lying."""
    ranks = rank_entities([
        played("a", share=0.3, events=80, momentum=0.01),
        played("b", share=0.1, events=20, momentum=-0.02),
        played("c", share=0.05, events=9, momentum=None),
    ])
    for row in ranks.values():
        total = row.presence_points + row.breadth_points + row.momentum_points
        assert row.score == pytest.approx(total, abs=0.15)


def test_every_score_is_inside_the_scale():
    ranks = rank_entities([
        played("a", share=0.3, events=80, momentum=1.0),      # far past the clamp
        played("b", share=0.0001, events=1, momentum=-1.0),
        dormant("z"),
    ])
    assert all(0.0 <= row.score <= 100.0 for row in ranks.values())


def test_an_empty_field_does_not_divide_by_zero():
    assert rank_entities([]) == {}
    ranks = rank_entities([played("only", share=0.0, events=0, momentum=None)])
    assert 0.0 <= ranks["only"].score <= 100.0


# -- momentum -----------------------------------------------------------------


def test_unknown_momentum_scores_the_middle_not_the_bottom():
    """Absence of evidence about direction is not evidence of decline."""
    assert momentum_points(None) == MOMENTUM_UNKNOWN
    assert momentum_points(0.0) == pytest.approx(MOMENTUM_UNKNOWN)


def test_momentum_is_clamped_at_both_ends():
    assert momentum_points(MOMENTUM_CLAMP * 10) == momentum_points(MOMENTUM_CLAMP)
    assert momentum_points(-MOMENTUM_CLAMP * 10) == momentum_points(-MOMENTUM_CLAMP)
    assert momentum_points(MOMENTUM_CLAMP) == pytest.approx(1.0)
    assert momentum_points(-MOMENTUM_CLAMP) == pytest.approx(0.0)


def test_momentum_breaks_a_tie_between_equal_presence():
    ranks = rank_entities([
        played("rising", share=0.1, events=10, momentum=0.04),
        played("falling", share=0.1, events=10, momentum=-0.04),
    ])
    assert ranks["rising"].position < ranks["falling"].position
    assert ranks["rising"].score > ranks["falling"].score


# -- dormant entities ---------------------------------------------------------


def test_an_entity_with_no_lists_scores_zero_and_keeps_a_position():
    """The behaviour asked for: minimum score, still ranked, not discarded."""
    ranks = rank_entities([played("a", share=0.2, events=30), dormant("z")])
    assert ranks["z"].score == 0.0
    assert ranks["z"].position == 2
    assert ranks["z"].ranked is False


def test_dormant_entities_never_outrank_a_measured_one():
    ranks = rank_entities([
        dormant("z", prior_share=0.9, prior_momentum=0.05, last_seen="2026-08-01"),
        played("weak", share=0.0001, events=1, momentum=-0.05),
    ])
    assert ranks["weak"].position < ranks["z"].position


def test_dormant_entities_are_ordered_by_prior_share():
    """Measured on the live snapshot: prior momentum is 0.00 for all of them, so this
    is the key that actually separates the dormant tail."""
    ranks = rank_entities([
        played("a", share=0.2, events=30),
        dormant("small", prior_share=0.003, prior_momentum=0.0),
        dormant("big", prior_share=0.015, prior_momentum=0.0),
        dormant("mid", prior_share=0.007, prior_momentum=0.0),
    ])
    order = sorted(("small", "big", "mid"), key=lambda k: ranks[k].position)
    assert order == ["big", "mid", "small"]


def test_prior_momentum_outranks_prior_share_when_it_discriminates():
    """The signal asked for wins when it says anything: climbing then vanishing beats
    flat and bigger."""
    ranks = rank_entities([
        dormant("climbing", prior_share=0.001, prior_momentum=0.03),
        dormant("flat", prior_share=0.020, prior_momentum=0.0),
    ])
    assert ranks["climbing"].position < ranks["flat"].position


def test_recency_breaks_a_tie_and_never_seen_sorts_last():
    ranks = rank_entities([
        dormant("old", prior_share=0.01, prior_momentum=0.0, last_seen="2026-01-01"),
        dormant("recent", prior_share=0.01, prior_momentum=0.0, last_seen="2026-08-01"),
        dormant("never", prior_share=0.01, prior_momentum=0.0, last_seen=""),
    ])
    order = sorted(("old", "recent", "never"), key=lambda k: ranks[k].position)
    assert order == ["recent", "old", "never"]


def test_a_dormant_entity_is_always_in_the_bottom_tier():
    """Even in a field small enough for a percentile to place it higher."""
    ranks = rank_entities([
        played("a", share=0.3, events=30),
        played("b", share=0.2, events=20),
        dormant("z", prior_share=0.5),
    ])
    assert ranks["z"].tier == TIER_LAST


def test_a_dormant_row_explains_itself_rather_than_showing_a_bare_zero():
    ranks = rank_entities([dormant("z", last_seen="2026-07-26")])
    summary = ranks["z"].summary
    assert "No lists in this range" in summary
    assert "2026-07-26" in summary


def test_a_ranked_row_shows_its_working():
    ranks = rank_entities([played("a", share=0.2, events=30, momentum=0.01)])
    summary = ranks["a"].summary
    assert "of 100" in summary
    assert "presence" in summary and "events" in summary and "momentum" in summary


# -- tiers and ordering -------------------------------------------------------


def test_tiers_are_proportions_of_the_field():
    total = 100
    assert tier_for(1, total) == "S"
    assert tier_for(12, total) == "S"
    assert tier_for(13, total) == "A"
    assert tier_for(total, total) == TIER_LAST
    assert TIER_ORDER == ("S", "A", "B", "C", "D")


def test_positions_are_dense_and_start_at_one():
    ranks = rank_entities([played(f"e{i}", share=0.1 - i * 0.01, events=10) for i in range(6)])
    assert sorted(r.position for r in ranks.values()) == [1, 2, 3, 4, 5, 6]


def test_score_order_and_position_order_agree():
    ranks = rank_entities([
        played("a", share=0.30, events=80, momentum=0.02),
        played("b", share=0.20, events=50, momentum=0.00),
        played("c", share=0.05, events=12, momentum=-0.03),
        dormant("z", prior_share=0.01),
    ])
    ordered = sorted(ranks.values(), key=lambda r: r.position)
    assert [r.entity_id for r in ordered] == ["a", "b", "c", "z"]
    scores = [r.score for r in ordered]
    assert all(x >= y for x, y in pairwise(scores))


def test_ties_break_on_name_so_a_rebuild_produces_the_same_wall():
    """Without an explicit tiebreak the order followed dictionary iteration, which is
    stable inside one process and not across a restart."""
    first = rank_entities([
        played("b", "Beta", share=0.1, events=10),
        played("a", "Alpha", share=0.1, events=10),
    ])
    second = rank_entities([
        played("a", "Alpha", share=0.1, events=10),
        played("b", "Beta", share=0.1, events=10),
    ])
    assert first["a"].position == second["a"].position == 1
    assert first["b"].position == second["b"].position == 2


# -- the grade curve ----------------------------------------------------------
#
# The rating is a presentation scale, not a second ranking. These pin the one property
# that makes that true — it cannot change the order — and the endpoints that make the
# scale mean something.


def test_the_curve_keeps_both_endpoints():
    assert grade(0.0) == 0.0
    assert grade(100.0) == pytest.approx(100.0)


def test_the_curve_is_strictly_increasing_so_it_cannot_reorder():
    """A curve applied to the total is a change of scale. Applied per component it
    would silently re-weight them against each other — measured, that reordered 18 of
    44 legends, which is why it is applied here instead."""
    graded = [grade(i / 4) for i in range(0, 401)]  # every quarter point of 0..100
    assert all(x < y for x, y in pairwise(graded))


def test_the_curve_lifts_the_middle_of_the_field():
    """The point of it: a fifth-placed legend read as 37 on the linear scale, which is
    a failing mark for a deck that is doing well."""
    assert GRADE_CURVE < 1.0
    assert grade(36.9) > 70
    assert grade(18.1) > 50


def test_ranking_order_survives_the_curve():
    field = [
        played("a", share=0.30, events=80, momentum=0.03),
        played("b", share=0.12, events=59, momentum=-0.01),
        played("c", share=0.045, events=31, momentum=-0.008),
        played("d", share=0.002, events=3, momentum=None),
        dormant("z", prior_share=0.01),
    ]
    ranks = rank_entities(field)
    ordered = sorted(ranks.values(), key=lambda r: r.position)
    assert [r.entity_id for r in ordered] == ["a", "b", "c", "d", "z"]
    assert all(x.score >= y.score for x, y in pairwise(ordered))


def test_the_parts_still_add_up_after_the_curve():
    """The curve scales the components by the same factor, so a card explaining itself
    stays arithmetically honest."""
    ranks = rank_entities([
        played("a", share=0.30, events=80, momentum=0.01),
        played("b", share=0.045, events=31, momentum=-0.008),
    ])
    for row in ranks.values():
        parts = row.presence_points + row.breadth_points + row.momentum_points
        assert row.score == pytest.approx(parts, abs=0.15)


def test_a_mid_field_legend_reads_as_a_grade_not_a_failure():
    """The behaviour asked for, end to end: fifth of a realistic field clears 70."""
    field = [
        played("kennen", share=0.1606, events=58, momentum=0.076),
        played("yi", share=0.1215, events=59, momentum=-0.013),
        played("irelia", share=0.0754, events=38, momentum=0.012),
        played("rengar", share=0.0545, events=33, momentum=-0.006),
        played("kaisa", share=0.0454, events=31, momentum=-0.008),
    ]
    ranks = rank_entities(field)
    assert ranks["kaisa"].position == 5
    assert ranks["kaisa"].score > 70
    assert ranks["kennen"].score > ranks["kaisa"].score
