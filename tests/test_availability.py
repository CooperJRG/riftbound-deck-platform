"""The two-mode availability model.

The behaviour these tests pin down is the direct answer to v2's
``strictBuildableEmptyResultRate: 0.814`` -- soft by default, so a card the player
lacks is de-emphasised rather than removed from consideration.
"""

from __future__ import annotations

import pytest

from riftbound.domain.availability import (
    DEFAULT_PENALTY,
    RULE_PROMO_ONLY,
    RULE_RARITY,
    RULE_SET,
    AvailabilityProfile,
    ExclusionRule,
    OwnedRule,
    deck_cost,
    deck_coverage,
)
from riftbound.domain.smart_decks import declared_knowledge

# -- open mode ----------------------------------------------------------------


def test_open_mode_makes_everything_fully_available(catalog):
    profile = AvailabilityProfile.open_profile()
    for card in catalog:
        state = profile.resolve(card)
        assert state.weight == 1.0
        assert state.max_copies is None
        assert state.available


# -- exclusion mode -----------------------------------------------------------


def test_excluded_card_is_de_emphasised_not_removed(catalog):
    """The onboarding case: "I don't have Seal of Discord"."""
    profile = AvailabilityProfile.from_exclusions(["harpoon-squad"])
    excluded = profile.resolve(catalog.get("harpoon-squad"))
    other = profile.resolve(catalog.get("brazen-buccaneer"))

    assert excluded.weight == pytest.approx(DEFAULT_PENALTY)
    assert excluded.available is True, "soft by default -- the builder may still use it"
    assert excluded.max_copies is None
    assert other.weight == 1.0


def test_strict_exclusion_removes_the_card(catalog):
    profile = AvailabilityProfile.from_exclusions(["harpoon-squad"], strict=True)
    state = profile.resolve(catalog.get("harpoon-squad"))
    assert state.weight == 0.0
    assert state.available is False
    assert state.max_copies == 0


def test_exclusion_rule_covers_a_whole_class(catalog):
    """One click instead of naming cards: "I don't have any Epics"."""
    profile = AvailabilityProfile.from_exclusions(rules=[ExclusionRule(RULE_RARITY, "Epic")])
    assert profile.resolve(catalog.get("harpoon-squad")).is_penalised  # Epic
    assert not profile.resolve(catalog.get("brazen-buccaneer")).is_penalised  # Common


def test_set_exclusion_rule(catalog):
    profile = AvailabilityProfile.from_exclusions(rules=[ExclusionRule(RULE_SET, "UNL")])
    assert profile.resolve(catalog.get("showcase-only")).is_penalised
    assert not profile.resolve(catalog.get("brazen-buccaneer")).is_penalised


def test_promo_only_rule_targets_cards_with_no_ordinary_printing(catalog):
    profile = AvailabilityProfile.from_exclusions(rules=[ExclusionRule(RULE_PROMO_ONLY)])
    assert profile.resolve(catalog.get("showcase-only")).is_penalised
    assert not profile.resolve(catalog.get("vi-destructive")).is_penalised


def test_exclusion_reason_is_machine_readable(catalog):
    profile = AvailabilityProfile.from_exclusions(rules=[ExclusionRule(RULE_RARITY, "Epic")])
    assert profile.resolve(catalog.get("harpoon-squad")).reason == "excluded:rarity=Epic"


def test_new_cards_are_available_by_default_in_exclusion_mode(catalog):
    """Self-healing across releases: a set the player has never heard of is usable."""
    profile = AvailabilityProfile.from_exclusions(["harpoon-squad"])
    brand_new = catalog.get("filler-01")
    assert profile.resolve(brand_new).weight == 1.0


# -- collection mode ----------------------------------------------------------


def test_owned_cards_are_full_weight(catalog):
    profile = AvailabilityProfile.from_collection({"brazen-buccaneer": 3})
    state = profile.resolve(catalog.get("brazen-buccaneer"))
    assert state.weight == 1.0
    assert state.owned_copies == 3


def test_unowned_cards_are_soft_by_default(catalog):
    """v2 made this a hard constraint and returned nothing 81% of the time."""
    profile = AvailabilityProfile.from_collection({"brazen-buccaneer": 3})
    state = profile.resolve(catalog.get("harpoon-squad"))
    assert state.weight == pytest.approx(DEFAULT_PENALTY)
    assert state.available is True


def test_strict_collection_caps_copies_at_what_is_owned(catalog):
    profile = AvailabilityProfile.from_collection({"brazen-buccaneer": 2}, strict=True)
    state = profile.resolve(catalog.get("brazen-buccaneer"))
    assert state.max_copies == 2
    assert profile.resolve(catalog.get("harpoon-squad")).available is False


def test_zero_quantities_are_treated_as_not_owned(catalog):
    profile = AvailabilityProfile.from_collection({"brazen-buccaneer": 0})
    assert profile.resolve(catalog.get("brazen-buccaneer")).owned_copies == 0


def test_explicit_zero_beats_a_bulk_rule_and_seeds_future_sessions(catalog):
    from riftbound.domain.availability import OwnedRule
    from riftbound.domain.smart_decks import declared_knowledge

    profile = AvailabilityProfile.from_collection(
        {"brazen-buccaneer": 0}, rules=[OwnedRule(kind="rarity", value="Common")],
    )
    assert profile.resolve(catalog.get("brazen-buccaneer")).weight < 1
    assert declared_knowledge(profile, catalog).exact["brazen-buccaneer"] == 0


# -- profile validation -------------------------------------------------------


def test_invalid_mode_is_rejected():
    with pytest.raises(ValueError, match="mode must be one of"):
        AvailabilityProfile(mode="nonsense")


def test_penalty_must_be_a_fraction():
    with pytest.raises(ValueError, match="penalty must be between"):
        AvailabilityProfile(mode="open", penalty=1.5)


# -- coverage reporting -------------------------------------------------------


def test_coverage_counts_penalised_copies(catalog):
    profile = AvailabilityProfile.from_exclusions(["harpoon-squad"])
    coverage = deck_coverage({"brazen-buccaneer": 3, "harpoon-squad": 2}, profile=profile, catalog=catalog)
    assert coverage.total_copies == 5
    assert coverage.available_copies == 3
    assert coverage.penalised_copies == 2
    assert coverage.missing == (("harpoon-squad", 2, "excluded:card"),)


def test_coverage_reports_partial_ownership(catalog):
    profile = AvailabilityProfile.from_collection({"brazen-buccaneer": 1})
    coverage = deck_coverage({"brazen-buccaneer": 3}, profile=profile, catalog=catalog)
    assert coverage.available_copies == 1
    assert coverage.missing == (("brazen-buccaneer", 2, "not-enough-copies"),)


def test_coverage_reports_unknown_cards_rather_than_dropping_them(catalog):
    """A card removed by a data refresh must be surfaced, not silently deleted."""
    profile = AvailabilityProfile.open_profile()
    coverage = deck_coverage({"card-that-no-longer-exists": 2}, profile=profile, catalog=catalog)
    assert coverage.missing == (("card-that-no-longer-exists", 2, "unknown-card"),)


def test_coverage_of_a_fully_available_deck_is_complete(catalog):
    coverage = deck_coverage(
        {"brazen-buccaneer": 3}, profile=AvailabilityProfile.open_profile(), catalog=catalog
    )
    assert coverage.is_complete
    assert coverage.ratio == 1.0


def test_describe_is_human_readable(catalog):
    assert "every card" in AvailabilityProfile.open_profile().describe()
    exclusion = AvailabilityProfile.from_exclusions(
        ["harpoon-squad"], [ExclusionRule(RULE_RARITY, "Epic")]
    )
    text = exclusion.describe()
    assert "De-emphasising" in text and "1 card" in text and "no Epic cards" in text
    assert "Excluding" in AvailabilityProfile.from_exclusions(["x"], strict=True).describe()


# -- saying what you *do* have -------------------------------------------------


def test_an_owned_rule_covers_a_whole_class_in_one_click(catalog):
    """The entry path that did not exist.

    "My collection" told the player to record what they own and gave them nowhere to do
    it: the only writer was the wizard's opt-in write-back, so a collection could only
    ever hold cards some session happened to ask about. Naming what you lack is the
    right shape for somebody who owns nearly everything; a casual player would have to
    list thousands of cards to say something true about a few hundred.
    """
    profile = AvailabilityProfile.from_collection(
        {}, rules=[OwnedRule("rarity", "Common")]
    )
    common = catalog.get("brazen-buccaneer")
    epic = catalog.get("harpoon-squad")
    assert profile.resolve(common).available
    assert not profile.resolve(common).is_penalised
    assert profile.resolve(epic).is_penalised, "a rule says nothing about other rarities"


def test_a_counted_card_beats_a_rule_about_it(catalog):
    """A rule is a broad statement; a count is a specific one, so the count wins."""
    profile = AvailabilityProfile.from_collection(
        {"brazen-buccaneer": 1}, rules=[OwnedRule("rarity", "Common")]
    )
    resolved = profile.resolve(catalog.get("brazen-buccaneer"))
    assert resolved.owned_copies == 1
    assert resolved.reason == "owned"


def test_a_rule_declares_a_bound_not_a_count(catalog):
    """"I have the commons" is not "I have exactly three of each".

    Seeded as a lower bound, which is what :mod:`smart_decks.knowledge` already means by
    "I have all of them" -- and it leaves room for somebody holding more than a playset
    without being written down as short of their own cards.
    """
    profile = AvailabilityProfile.from_collection(
        {}, rules=[OwnedRule("rarity", "Common")]
    )
    knowledge = declared_knowledge(profile, catalog)
    assert knowledge.lower_bound("brazen-buccaneer") == 3
    assert not knowledge.is_exact("brazen-buccaneer"), "a bound, not a count"


def test_runes_are_declared_in_bulk(catalog):
    """A rune base wants twelve, and runes are bought in bulk or not at all.

    Declaring three would tell a player they were short of the runes they just said
    they had.
    """
    profile = AvailabilityProfile.from_collection(
        {}, rules=[OwnedRule("rarity", "Common")]
    )
    knowledge = declared_knowledge(profile, catalog)
    assert knowledge.lower_bound("fury-rune") == 12


def test_an_owned_rule_reads_as_a_positive_statement():
    assert OwnedRule("rarity", "Common").describe() == "all Commons"
    assert ExclusionRule("rarity", "Common").describe() == "no Common cards"


# -- what a deck costs ---------------------------------------------------------


def test_a_bill_names_the_scarce_cards_first(catalog):
    """"Needs 3 Epics" is the sentence somebody balks at; lead with it."""
    profile = AvailabilityProfile.from_exclusions(rules=[ExclusionRule("rarity", "Epic")])
    cost = deck_cost(
        {"harpoon-squad": 3, "brazen-buccaneer": 3}, profile=profile, catalog=catalog
    )
    assert cost.short == {"Epic": 3}
    assert cost.describe() == "Needs 3 Epics you do not have."
    assert not cost.is_affordable
    assert cost.scarce_short == 3


def test_a_deck_you_can_field_says_so_rather_than_billing_you_nothing(catalog):
    profile = AvailabilityProfile.open_profile()
    cost = deck_cost({"brazen-buccaneer": 3}, profile=profile, catalog=catalog)
    assert cost.is_affordable
    assert cost.describe() == "You can field this deck."


def test_composition_is_reported_with_no_collection_at_all(catalog):
    """The day-zero property.

    On the release day of a new set there is no meta evidence, no play rate and quite
    possibly no collection. Rarity is printed on the card, so it is the one
    accessibility signal that exists before anything has been played -- and it has to
    survive an empty profile to be worth anything then.
    """
    cost = deck_cost(
        {"harpoon-squad": 3, "brazen-buccaneer": 3},
        profile=AvailabilityProfile.open_profile(),
        catalog=catalog,
    )
    assert cost.short == {}, "we cannot bill for cards we have no reason to think missing"
    assert cost.composition == {"Epic": 3, "Common": 3}


def test_the_bill_and_the_coverage_readout_cannot_disagree(catalog):
    """Built on deck_coverage rather than beside it.

    Two independent walks of the same deck are two chances to answer "which cards are
    missing" differently, and the player sees both numbers at once.
    """
    profile = AvailabilityProfile.from_exclusions(rules=[ExclusionRule("rarity", "Epic")])
    counts = {"harpoon-squad": 3, "brazen-buccaneer": 3, "singular-relic": 1}
    cost = deck_cost(counts, profile=profile, catalog=catalog)
    coverage = deck_coverage(counts, profile=profile, catalog=catalog)
    assert cost.copies_short == sum(c for _, c, _ in coverage.missing)


def test_an_unknown_card_is_billed_rather_than_dropped(catalog):
    """A card the bundle does not know is a data problem to surface, not to hide."""
    cost = deck_cost(
        {"no-such-card": 2}, profile=AvailabilityProfile.open_profile(), catalog=catalog
    )
    assert cost.short == {"Unknown": 2}
