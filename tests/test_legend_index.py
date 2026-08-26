"""What the meta knows about one legend."""

from __future__ import annotations

import pytest

from riftbound.domain.deck import Deck
from riftbound.domain.legend_index import (
    CLUSTER_THRESHOLD,
    build_index,
    build_profile,
    cost_band,
    substitutes,
)
from riftbound.domain.meta import MetaDeck, Provenance

LEGEND = "vi-piltover-enforcer"


def meta_deck(deck_id: str, main: dict[str, int], **overrides) -> MetaDeck:
    payload = {
        "runes": {"fury-rune": 12},
        "battlefields": ["the-arena", "the-forge", "the-spire"],
    }
    payload.update(overrides)
    return MetaDeck(
        deck=Deck.make(
            legend_id=LEGEND, champion_id="vi-destructive", main=main,
            runes=payload["runes"], battlefields=payload["battlefields"],
        ),
        provenance=Provenance(source="t", source_slug=deck_id, url=""),
    )


def spread(*card_ids: str, copies: int = 3) -> dict[str, int]:
    return {c: copies for c in card_ids}


# -- play rate and copies -----------------------------------------------------


def test_play_rate_is_the_share_of_decks_playing_a_card():
    decks = [
        meta_deck("a", spread("brazen-buccaneer", "filler-01")),
        meta_deck("b", spread("brazen-buccaneer", "filler-02")),
    ]
    profile = build_profile(LEGEND, decks, {"a": 1.0, "b": 1.0})
    assert profile.play_rate["brazen-buccaneer"] == pytest.approx(1.0)
    assert profile.play_rate["filler-01"] == pytest.approx(0.5)


def test_better_decks_count_for_more():
    """A card played by winners should outrank one played by also-rans."""
    decks = [
        meta_deck("winner", spread("harpoon-squad")),
        meta_deck("loser", spread("filler-01")),
    ]
    profile = build_profile(LEGEND, decks, {"winner": 1.0, "loser": 0.1})
    assert profile.play_rate["harpoon-squad"] > profile.play_rate["filler-01"]


def test_copies_reflect_what_the_field_actually_runs():
    """Some cards are three-ofs and some are one-ofs; the build should know."""
    decks = [
        meta_deck("a", {"brazen-buccaneer": 3, "singular-relic": 1}),
        meta_deck("b", {"brazen-buccaneer": 3, "singular-relic": 1}),
    ]
    profile = build_profile(LEGEND, decks, {"a": 1.0, "b": 1.0})
    assert profile.copies["brazen-buccaneer"] == 3
    assert profile.copies["singular-relic"] == 1


def test_a_profile_feeds_the_constructor_directly():
    decks = [meta_deck("a", spread("brazen-buccaneer"))]
    preference = build_profile(LEGEND, decks, {"a": 1.0}).preference()
    assert preference.rank("brazen-buccaneer") > preference.rank("filler-01")
    assert preference.wanted("brazen-buccaneer") == 3


# -- clusters -----------------------------------------------------------------


def test_near_identical_decks_form_one_family():
    shared = spread(*[f"filler-{i:02d}" for i in range(1, 10)])
    decks = [
        meta_deck("a", {**shared, "brazen-buccaneer": 3}),
        meta_deck("b", {**shared, "harpoon-squad": 3}),
    ]
    profile = build_profile(LEGEND, decks, {"a": 1.0, "b": 0.9})
    assert len(profile.clusters) == 1
    assert profile.clusters[0].size == 2


def test_different_plans_form_different_families():
    decks = [
        meta_deck("a", spread(*[f"filler-{i:02d}" for i in range(1, 6)])),
        meta_deck("b", spread(*[f"filler-{i:02d}" for i in range(9, 14)])),
    ]
    profile = build_profile(LEGEND, decks, {"a": 1.0, "b": 0.9})
    assert len(profile.clusters) == 2


def test_a_cluster_separates_its_core_from_its_flex():
    """The core is the deck's identity; only flex may be swapped in a repair."""
    shared = spread(*[f"filler-{i:02d}" for i in range(1, 10)])
    decks = [
        meta_deck("a", {**shared, "brazen-buccaneer": 3}),
        meta_deck("b", {**shared, "harpoon-squad": 3}),
    ]
    cluster = build_profile(LEGEND, decks, {"a": 1.0, "b": 0.9}).clusters[0]
    assert "filler-01" in cluster.core, "played by every deck in the family"
    assert "brazen-buccaneer" in cluster.flex, "played by half of them"
    assert not (cluster.core & cluster.flex)


def test_clusters_are_ranked_by_their_best_deck():
    decks = [
        meta_deck("weak", spread(*[f"filler-{i:02d}" for i in range(1, 6)])),
        meta_deck("strong", spread(*[f"filler-{i:02d}" for i in range(9, 14)])),
    ]
    profile = build_profile(LEGEND, decks, {"weak": 0.2, "strong": 0.9})
    assert profile.clusters[0].cluster_id == "strong"


def test_a_deck_can_be_traced_to_its_family():
    decks = [meta_deck("a", spread("brazen-buccaneer"))]
    profile = build_profile(LEGEND, decks, {"a": 1.0})
    assert profile.cluster_of("a") is not None
    assert profile.cluster_of("nope") is None


def test_the_threshold_sits_between_the_measured_median_and_p90():
    """Across the snapshot, the median deck pair overlaps at 0.57 and p90 near 0.85."""
    assert 0.57 < CLUSTER_THRESHOLD < 0.85


# -- affinity -----------------------------------------------------------------


def test_affinity_finds_what_gets_played_together():
    decks = [
        meta_deck("a", spread("brazen-buccaneer", "harpoon-squad")),
        meta_deck("b", spread("brazen-buccaneer", "harpoon-squad")),
        meta_deck("c", spread("brazen-buccaneer", "filler-01")),
    ]
    profile = build_profile(LEGEND, decks, {"a": 1.0, "b": 1.0, "c": 1.0})
    together = profile.affinity("harpoon-squad", ["brazen-buccaneer"])
    apart = profile.affinity("filler-01", ["brazen-buccaneer"])
    assert together > apart


def test_lift_separates_deliberate_pairing_from_coincidence():
    """A card in every deck co-occurs with everything; lift should not reward that."""
    decks = [
        meta_deck("a", spread("filler-01", "brazen-buccaneer")),
        meta_deck("b", spread("filler-01", "harpoon-squad")),
    ]
    profile = build_profile(LEGEND, decks, {"a": 1.0, "b": 1.0})
    assert profile.lift("filler-01", ["brazen-buccaneer"]) == pytest.approx(1.0, abs=0.01)


def test_affinity_with_no_context_falls_back_to_play_rate():
    decks = [meta_deck("a", spread("brazen-buccaneer"))]
    profile = build_profile(LEGEND, decks, {"a": 1.0})
    assert profile.affinity("brazen-buccaneer", []) == profile.play_rate["brazen-buccaneer"]


# -- substitutes --------------------------------------------------------------


def test_substitutes_prefer_cards_the_field_plays_alongside(catalog):
    decks = [
        meta_deck("a", spread("brazen-buccaneer", "harpoon-squad")),
        meta_deck("b", spread("brazen-buccaneer", "harpoon-squad")),
        meta_deck("c", spread("brazen-buccaneer", "filler-01")),
    ]
    profile = build_profile(LEGEND, decks, {"a": 1.0, "b": 1.0, "c": 1.0})
    owned = {"harpoon-squad": 3, "filler-01": 3}
    ranked = substitutes(
        "showcase-only", profile=profile, owned=owned, catalog=catalog,
        context=["brazen-buccaneer"],
    )
    assert ranked[0][0] == "harpoon-squad"


def test_substitutes_skip_what_you_do_not_own(catalog):
    decks = [meta_deck("a", spread("brazen-buccaneer", "harpoon-squad"))]
    profile = build_profile(LEGEND, decks, {"a": 1.0})
    ranked = substitutes(
        "showcase-only", profile=profile, owned={"harpoon-squad": 0},
        catalog=catalog, context=["brazen-buccaneer"],
    )
    assert ranked == []


def test_substitutes_can_exclude_cards_already_in_the_deck(catalog):
    decks = [meta_deck("a", spread("brazen-buccaneer", "harpoon-squad"))]
    profile = build_profile(LEGEND, decks, {"a": 1.0})
    ranked = substitutes(
        "showcase-only", profile=profile, owned={"harpoon-squad": 3},
        catalog=catalog, context=["brazen-buccaneer"], exclude=["harpoon-squad"],
    )
    assert ranked == []


# -- roles --------------------------------------------------------------------


@pytest.mark.parametrize("cost,expected", [(0, (0, 2)), (2, (0, 2)), (3, (3, 4)), (9, (7, 99))])
def test_cost_bands(cost, expected):
    assert cost_band(cost) == expected


def test_a_missing_cost_lands_in_the_cheapest_band():
    """Legends and battlefields have no cost; they must not sort as expensive."""
    assert cost_band(None) == (0, 2)


# -- the index ----------------------------------------------------------------


def test_the_index_profiles_every_legend_present():
    decks = [meta_deck("a", spread("brazen-buccaneer"))]
    other = MetaDeck(
        deck=Deck.make(legend_id="other-legend", main={"filler-01": 3}),
        provenance=Provenance(source="t", source_slug="b", url=""),
    )
    index = build_index(decks + [other], {"a": 1.0, "b": 0.5})
    assert set(index.profiles) == {LEGEND, "other-legend"}
    assert index.legends()[0] == LEGEND, "ordered by deck count"


def test_an_unknown_legend_yields_an_empty_preference():
    index = build_index([], {})
    assert index.get("nope") is None
    assert index.preference_for("nope").rank("anything") == 0.0
