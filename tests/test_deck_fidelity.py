"""Building the format that is actually being played.

The archive spans a banning, so a third of it describes a format nobody plays. Built over
all of it, the builder's preference signal was an average of two formats and the player
got the average — a legal deck, assembled from obsolete evidence, with no symptom
anywhere. Smart Decks hit every one of its targets throughout.

What is pinned here:

* the index is scoped to one era, and a profile says which era it came from;
* a legend with no lists in the era falls back rather than vanishing — and is *labelled*,
  never passed off as current;
* there is no evidence threshold on the scoping, because measurement said a threshold
  makes it worse;
* the fidelity metric can tell a matching deck from a mismatched one, which is what makes
  it usable as a gate.
"""

from __future__ import annotations

import pytest

from conftest import make_card
from riftbound.domain.cards import build_catalog
from riftbound.domain.deck import Deck
from riftbound.domain.deck_fidelity import (
    MIN_REAL_LISTS,
    FidelityReport,
    LegendFidelity,
    compare,
    full_collection,
    jaccard,
    measure,
    peer_ceiling,
)
from riftbound.domain.eras import eras_from
from riftbound.domain.legend_index import build_index, build_scoped_index
from riftbound.domain.meta import EVIDENCE_TOURNAMENT_PLACED, MetaDeck, Provenance
from riftbound.domain.rules import FormatRules

LEGEND = "vi-piltover-enforcer"
CHAMPION = "vi-destructive"

#: Two disjoint packages, so "built from the old evidence" and "built from the new" are
#: distinguishable at a glance rather than by a decimal place.
OLD = [f"old-{i:02d}" for i in range(1, 14)]
NEW = [f"new-{i:02d}" for i in range(1, 14)]

CATALOG = build_catalog(
    [
        make_card(LEGEND, "Vi - Piltover Enforcer", card_type="Legend",
                  champion_tags=("Vi",), cost=None, might=None),
        make_card(CHAMPION, "Vi - Destructive", super_type="Champion", champion_tags=("Vi",)),
        *[make_card(c, c.title()) for c in OLD],
        *[make_card(c, c.title()) for c in NEW],
        make_card("fury-rune", "Fury Rune", card_type="Rune", cost=None, might=None),
        *[make_card(b, b.title(), card_type="Battlefield", cost=None, might=None)
          for b in ("the-arena", "the-forge", "the-spire")],
    ]
)

RULES = FormatRules(
    format_name="constructed",
    description="fidelity fixture",
    constraints={
        "legend_required": True, "legend_card_type": "Legend",
        "chosen_champion_required": True, "champion_super_type": "Champion",
        "main_deck_size_exact": 40, "rune_count_exact": 12,
        "battlefield_count_exact": 3, "battlefield_unique_required": True,
        "main_copy_limit": 3, "domain_identity_enforced": True,
        "rune_card_type": "Rune", "battlefield_card_type": "Battlefield",
        "allowed_main_card_types": ["Unit", "Gear", "Spell"],
        "banned_cards": [],
    },
    rule_refs={},
).bind(CATALOG)

ERAS = eras_from({
    "periods": [
        {"id": "launch", "name": "Launch", "to": "2026-03-28"},
        {"id": "post-ban", "name": "Post ban", "from": "2026-03-29"},
    ]
})
CURRENT = ERAS.current


def a_deck(index: int, when: str, cards: list[str], legend: str = LEGEND) -> MetaDeck:
    main = {CHAMPION: 3}
    main.update({c: 3 for c in cards})
    return MetaDeck(
        deck=Deck.make(
            name=f"list-{index}", legend_id=legend, champion_id=CHAMPION, main=main,
            runes={"fury-rune": 12},
            battlefields=["the-arena", "the-forge", "the-spire"],
        ),
        provenance=Provenance(
            source="t", source_slug=f"{when}-{index}", url="",
            evidence=EVIDENCE_TOURNAMENT_PLACED, tournament_slug=f"ev-{when}",
            tournament_date=when, published_at=when, placement=1, field_size=64,
        ),
    )


def a_field(*, old: int, new: int, legend: str = LEGEND) -> list[MetaDeck]:
    return [
        *[a_deck(i, "2026-02-02", OLD, legend) for i in range(old)],
        *[a_deck(100 + i, "2026-06-02", NEW, legend) for i in range(new)],
    ]


def scores_for(decks) -> dict[str, float]:
    return {d.deck_id: 1.0 for d in decks}


# -- scoping ------------------------------------------------------------------


def test_the_index_is_built_from_one_era_and_says_which():
    decks = a_field(old=20, new=20)
    index = build_scoped_index(decks, scores_for(decks), CURRENT)
    profile = index.get(LEGEND)
    assert profile.era_id == "post-ban"
    assert profile.deck_count == 20  # the current era's lists only


def test_the_scoped_signal_prefers_what_the_era_plays():
    """The defect, in one assertion: a legend whose old lists outnumber its new ones."""
    decks = a_field(old=40, new=10)
    scores = scores_for(decks)

    everything = build_index(decks, scores, era_id="all").get(LEGEND)
    scoped = build_scoped_index(decks, scores, CURRENT).get(LEGEND)

    # The all-time signal is dominated by the dead format...
    assert everything.play_rate[OLD[0]] > everything.play_rate[NEW[0]]
    # ...and the scoped one does not know it exists.
    assert scoped.play_rate[NEW[0]] > 0
    assert scoped.play_rate.get(OLD[0], 0.0) == 0.0


def test_a_legend_with_nothing_in_this_era_falls_back_and_is_labelled():
    """Never silently: an all-time profile presented as current is the original bug."""
    decks = [
        *a_field(old=10, new=10),
        *[a_deck(200 + i, "2026-02-02", OLD, "dormant-legend") for i in range(6)],
    ]
    index = build_scoped_index(decks, scores_for(decks), CURRENT)

    assert index.get(LEGEND).era_id == "post-ban"
    stale = index.get("dormant-legend")
    assert stale is not None, "a legend absent from the era must not vanish"
    assert stale.era_id == "all"
    assert stale.deck_count == 6


def test_there_is_no_evidence_threshold_on_scoping():
    """Measured on the live snapshot: requiring 10 era decks before trusting them drops
    the closest-match score from 0.879 to 0.875, and requiring 30 drops it to 0.855.
    Eight current lists beat thirty-seven pre-ban ones, so a single current list is
    still preferred to the whole archive."""
    decks = a_field(old=50, new=1)
    profile = build_scoped_index(decks, scores_for(decks), CURRENT).get(LEGEND)
    assert profile.era_id == "post-ban"
    assert profile.deck_count == 1
    assert profile.play_rate.get(OLD[0], 0.0) == 0.0


def test_scoping_to_all_time_keeps_everything():
    decks = a_field(old=10, new=10)
    index = build_scoped_index(decks, scores_for(decks), ERAS.resolve("all"))
    assert index.get(LEGEND).deck_count == 20
    assert index.get(LEGEND).era_id == "all"


# -- the metric ---------------------------------------------------------------


def test_jaccard_is_over_the_card_set_not_the_copies():
    """Two lists differing only in a 2-of versus a 3-of are the same deck."""
    assert jaccard({"a", "b"}, {"a", "b"}) == 1.0
    assert jaccard({"a", "b"}, {"a"}) == pytest.approx(0.5)
    assert jaccard(set(), set()) == 0.0


def test_a_full_collection_removes_the_collection_constraint():
    owned = full_collection(LEGEND, catalog=CATALOG, rules=RULES)
    assert owned[LEGEND] == 1
    assert owned[NEW[0]] == 3
    assert owned["fury-rune"] >= 12


def test_fidelity_rises_when_the_signal_matches_the_reference():
    """The property that makes this usable as a gate: it can tell the two apart."""
    decks = a_field(old=40, new=12)
    scores = scores_for(decks)
    reference = [d for d in decks if CURRENT.contains(d.provenance.tournament_date)]

    stale = measure(
        index=build_index(decks, scores, era_id="all"),
        reference=reference, catalog=CATALOG, rules=RULES,
    )
    scoped = measure(
        index=build_scoped_index(decks, scores, CURRENT),
        reference=reference, catalog=CATALOG, rules=RULES,
    )
    assert scoped.best_match > stale.best_match
    delta = compare(stale, scoped)
    assert delta["wins"] >= 1
    assert delta["losses"] == 0


def test_a_legend_with_too_few_real_lists_is_not_measured():
    """Below the floor the 'field' is one or two decks, and the number would describe
    those decks rather than the builder."""
    decks = a_field(old=0, new=MIN_REAL_LISTS - 1)
    report = measure(
        index=build_scoped_index(decks, scores_for(decks), CURRENT),
        reference=decks, catalog=CATALOG, rules=RULES,
    )
    assert report.rows == ()
    assert report.best_match == 0.0


def test_the_report_names_its_worst_legends():
    decks = a_field(old=0, new=10)
    report = measure(
        index=build_scoped_index(decks, scores_for(decks), CURRENT),
        reference=decks, catalog=CATALOG, rules=RULES,
    )
    assert report.legends == 1
    worst = report.worst(3)
    assert worst[0].name == "Vi - Piltover Enforcer"
    assert "closest real list" in worst[0].describe()


# -- the ceiling ---------------------------------------------------------------
#
# A raw fidelity score cannot be read on its own, and the first cut of this module
# invited exactly that mistake: it printed the lowest scores as "furthest from the
# field", which read as a list of the builder's failures. Measured, the correlation
# between a raw score and how much a legend's own lists agree with each other is +0.730 —
# the list was ranking fragmentation. Renata Glasc topped it while being the strongest
# relative result in the format: 0.58 against a ceiling of 0.34.


def test_the_ceiling_is_what_a_real_list_scores_against_its_nearest_peer():
    identical = [frozenset({"a", "b", "c"})] * 3
    assert peer_ceiling(identical) == pytest.approx(1.0)

    disjoint = [frozenset({"a"}), frozenset({"b"}), frozenset({"c"})]
    assert peer_ceiling(disjoint) == pytest.approx(0.0)


def test_a_single_list_has_no_peer_and_so_no_ceiling():
    assert peer_ceiling([frozenset({"a"})]) == 0.0
    assert peer_ceiling([]) == 0.0


def test_a_fragmented_field_has_a_lower_ceiling_than_a_settled_one():
    """The property the whole correction rests on: some legends are simply harder."""
    settled = [frozenset(OLD), frozenset(OLD), frozenset([*OLD[:-1], "new-01"])]
    split = [frozenset(OLD), frozenset(NEW), frozenset([*OLD[:6], *NEW[:6]])]
    assert peer_ceiling(settled) > peer_ceiling(split)


def test_the_worst_list_ranks_by_margin_not_by_raw_score():
    """Ranked raw, a legend nobody can match tops the list while we are doing well."""
    hard = LegendFidelity(
        legend_id="hard", name="Hard", real_lists=10,
        best_match=0.58, mean_match=0.40, ceiling=0.34,     # +0.24 — our best result
    )
    easy = LegendFidelity(
        legend_id="easy", name="Easy", real_lists=10,
        best_match=0.86, mean_match=0.70, ceiling=0.91,     # -0.05 — a genuine miss
    )
    report = FidelityReport(rows=(hard, easy))

    assert report.worst(1)[0].legend_id == "easy"
    assert [r.legend_id for r in report.below_ceiling] == ["easy"]
    assert hard.margin > 0 > easy.margin


def test_a_row_describes_itself_against_its_ceiling():
    row = LegendFidelity(
        legend_id="l", name="Legend", real_lists=10,
        best_match=0.58, mean_match=0.40, ceiling=0.34,
    )
    text = row.describe()
    assert "58%" in text and "34%" in text and "+24%" in text


def test_measure_attaches_a_ceiling_to_every_row():
    decks = a_field(old=0, new=10)
    report = measure(
        index=build_scoped_index(decks, scores_for(decks), CURRENT),
        reference=decks, catalog=CATALOG, rules=RULES,
    )
    assert report.legends == 1
    row = report.rows[0]
    assert row.ceiling > 0, "identical published lists must not have a zero ceiling"
    assert report.ceiling == pytest.approx(row.ceiling)
    assert report.margin == pytest.approx(row.margin)
