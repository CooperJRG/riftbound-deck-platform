"""Deck legality against a data-driven format profile."""

from __future__ import annotations

from riftbound.domain.deck import Deck
from riftbound.domain.validator import SEVERITY_WARNING, validate


def codes(result) -> set[str]:
    return {i.code for i in result.issues}


def test_a_legal_deck_is_legal(legal_deck, bound_rules, catalog):
    result = validate(legal_deck, rules=bound_rules, catalog=catalog)
    assert result.legal, [i.message for i in result.errors]
    assert result.main_total == 40
    assert result.rune_total == 12
    assert result.battlefield_count == 3


def test_issues_cite_the_rulebook(legal_deck, bound_rules, catalog):
    """The property worth keeping from v2: every message can say why."""
    deck = legal_deck.with_card("filler-01", 1)  # 40 -> 38
    result = validate(deck, rules=bound_rules, catalog=catalog)
    issue = next(i for i in result.issues if i.code == "MAIN_SIZE")
    assert issue.rule_refs == ("TR 402.1", "TR 601.1.b")


def test_wrong_main_deck_size_is_reported(legal_deck, bound_rules, catalog):
    deck = legal_deck.with_card("brazen-buccaneer", 1)
    result = validate(deck, rules=bound_rules, catalog=catalog)
    assert "MAIN_SIZE" in codes(result)
    assert not result.legal


def test_copy_limit_is_enforced(legal_deck, bound_rules, catalog):
    deck = legal_deck.with_card("brazen-buccaneer", 4)
    result = validate(deck, rules=bound_rules, catalog=catalog)
    assert "MAIN_COPY_LIMIT" in codes(result)


def test_unique_cards_are_limited_to_one(legal_deck, bound_rules, catalog):
    deck = legal_deck.with_card("singular-relic", 2)
    result = validate(deck, rules=bound_rules, catalog=catalog)
    issue = next(i for i in result.issues if i.code == "MAIN_COPY_LIMIT")
    assert "unique" in issue.message
    assert issue.card_id == "singular-relic"


def test_domain_identity_is_enforced_against_the_legend(legal_deck, bound_rules, catalog):
    """Calm Intruder is outside a Fury legend's identity."""
    deck = legal_deck.with_card("filler-01", 0).with_card("calm-intruder", 3)
    result = validate(deck, rules=bound_rules, catalog=catalog)
    assert "MAIN_DOMAIN" in codes(result)


def test_runes_must_match_domain_identity(legal_deck, bound_rules, catalog):
    deck = legal_deck.with_card("fury-rune", 6, zone="runes").with_card("calm-rune", 6, zone="runes")
    result = validate(deck, rules=bound_rules, catalog=catalog)
    assert "RUNES_DOMAIN" in codes(result)


def test_wrong_card_type_in_a_zone_is_reported(legal_deck, bound_rules, catalog):
    deck = legal_deck.with_card("fury-rune", 3)  # a Rune in the main deck
    result = validate(deck, rules=bound_rules, catalog=catalog)
    assert "MAIN_CARD_TYPE" in codes(result)


def test_battlefields_must_be_unique(legal_deck, bound_rules, catalog):
    deck = legal_deck.with_meta(battlefields=("the-arena", "the-arena", "the-forge"))
    result = validate(deck, rules=bound_rules, catalog=catalog)
    assert "BATTLEFIELD_DUPLICATE" in codes(result)


def test_battlefield_count_is_exact(legal_deck, bound_rules, catalog):
    deck = legal_deck.with_meta(battlefields=("the-arena", "the-forge"))
    result = validate(deck, rules=bound_rules, catalog=catalog)
    assert "BATTLEFIELD_COUNT" in codes(result)


def test_chosen_champion_must_be_in_the_main_deck(legal_deck, bound_rules, catalog):
    deck = legal_deck.with_card("vi-destructive", 0).with_card("filler-01", 6)
    result = validate(deck, rules=bound_rules, catalog=catalog)
    assert "CHAMPION_NOT_IN_MAIN" in codes(result)


def test_champion_must_share_a_tag_with_the_legend(legal_deck, bound_rules, catalog):
    deck = legal_deck.with_meta(champion_id="brazen-buccaneer")
    result = validate(deck, rules=bound_rules, catalog=catalog)
    assert "CHAMPION_TYPE" in codes(result)


def test_missing_legend_is_reported(legal_deck, bound_rules, catalog):
    deck = legal_deck.with_meta(legend_id="")
    result = validate(deck, rules=bound_rules, catalog=catalog)
    assert "LEGEND_REQUIRED" in codes(result)


def test_banned_cards_are_rejected_from_the_profile_not_from_code(legal_deck, bound_rules, catalog):
    deck = legal_deck.with_card("filler-01", 0).with_card("banned-blade", 3)
    result = validate(deck, rules=bound_rules, catalog=catalog)
    assert "BANNED" in codes(result)


def test_ban_list_resolves_names_to_ids_and_reports_failures(rules, catalog):
    bound = rules.bind(catalog)
    assert bound.banned_card_ids == {"banned-blade"}
    assert bound.unresolved_bans == ()


def test_unresolvable_ban_names_are_surfaced(rules, catalog):
    profile = rules.__class__(
        format_name="constructed",
        description="",
        constraints={**rules.constraints, "banned_cards": ["No Such Card"]},
        rule_refs=rules.rule_refs,
    )
    bound = profile.bind(catalog)
    assert bound.unresolved_bans == ("No Such Card",)


def test_sideboard_size_limit(legal_deck, bound_rules, catalog):
    deck = legal_deck.with_meta(sideboard={"brazen-buccaneer": 9})
    result = validate(deck, rules=bound_rules, catalog=catalog)
    assert "SIDEBOARD_SIZE" in codes(result)


def test_combined_main_and_sideboard_copy_limit(legal_deck, bound_rules, catalog):
    deck = legal_deck.with_meta(sideboard={"brazen-buccaneer": 2})  # 3 main + 2 side
    result = validate(deck, rules=bound_rules, catalog=catalog)
    assert "COMBINED_COPY_LIMIT" in codes(result)


# -- resilience to data changes ----------------------------------------------


def test_unknown_card_is_a_warning_not_a_crash(legal_deck, bound_rules, catalog):
    """A deck saved before a data refresh must survive a card being renamed."""
    deck = legal_deck.with_card("card-removed-upstream", 1)
    result = validate(deck, rules=bound_rules, catalog=catalog)
    issue = next(i for i in result.issues if i.code == "UNKNOWN_CARD")
    assert issue.severity == SEVERITY_WARNING
    assert issue.card_id == "card-removed-upstream"
    assert "unchanged" in issue.message


def test_an_empty_deck_validates_without_raising(bound_rules, catalog):
    result = validate(Deck.make(), rules=bound_rules, catalog=catalog)
    assert not result.legal
    assert "LEGEND_REQUIRED" in codes(result)


def test_cards_with_unparseable_domains_do_not_block(legal_deck, bound_rules, catalog):
    """9 real cards have no colour field. They must not be judged out of identity."""
    from tests.conftest import make_card

    from riftbound.domain.cards import build_catalog

    odd = make_card("mystery-card", "Mystery Card", domains=(), domains_ok=False)
    wider = build_catalog([*list(catalog), odd])
    deck = legal_deck.with_card("filler-01", 0).with_card("mystery-card", 3)
    result = validate(deck, rules=bound_rules, catalog=wider)
    assert "MAIN_DOMAIN" not in codes(result)


# -- advisories ---------------------------------------------------------------


#: Ten sideboard cards spread over cards absent from the main deck, so the combined
#: main+sideboard copy limit does not fire and the test measures what it claims to.
SIDEBOARD_OF_10 = {"filler-10": 3, "filler-11": 3, "filler-12": 3, "filler-13": 1}


def advisory_rules(rules, catalog, *, allow=10, advise=8):
    """A profile that permits `allow` but cautions above `advise`."""
    return rules.__class__(
        format_name="constructed",
        description="",
        constraints={**rules.constraints, "sideboard_max": allow},
        rule_refs=rules.rule_refs,
        advisories={
            "sideboard_max": {
                "recommended_max": advise,
                "message": "Allowed here; trim to 8 before a sanctioned event.",
                "rule_refs": ["TR 601.1.c.1"],
            }
        },
    ).bind(catalog)


def test_a_relaxed_limit_no_longer_makes_a_deck_illegal(legal_deck, rules, catalog):
    """The field plays 10-card sideboards; the app must not reject them."""
    deck = legal_deck.with_meta(sideboard=SIDEBOARD_OF_10)
    result = validate(deck, rules=advisory_rules(rules, catalog), catalog=catalog)
    assert result.legal, [i.message for i in result.errors]
    assert "SIDEBOARD_SIZE" not in codes(result)


def test_but_it_still_says_so_before_you_play(legal_deck, rules, catalog):
    deck = legal_deck.with_meta(sideboard=SIDEBOARD_OF_10)
    result = validate(deck, rules=advisory_rules(rules, catalog), catalog=catalog)
    notice = next(i for i in result.notices if i.code == "SIDEBOARD_ADVISORY")
    assert "trim to 8" in notice.message
    assert notice.rule_refs == ("TR 601.1.c.1",)


def test_a_notice_never_makes_a_deck_illegal(legal_deck, rules, catalog):
    """Otherwise 'notice' is just a warning wearing a different hat."""
    deck = legal_deck.with_meta(sideboard=SIDEBOARD_OF_10)
    result = validate(deck, rules=advisory_rules(rules, catalog), catalog=catalog)
    assert result.notices
    assert result.legal
    assert result.errors == ()


def test_no_notice_when_the_deck_is_within_the_recommendation(legal_deck, rules, catalog):
    deck = legal_deck.with_meta(sideboard={"filler-10": 3})
    result = validate(deck, rules=advisory_rules(rules, catalog), catalog=catalog)
    assert result.notices == ()


def test_the_hard_limit_still_applies_above_the_relaxed_value(legal_deck, rules, catalog):
    """Relaxing 8 -> 10 is not the same as removing the limit."""
    deck = legal_deck.with_meta(sideboard={**SIDEBOARD_OF_10, "filler-14": 2})  # 12
    result = validate(deck, rules=advisory_rules(rules, catalog), catalog=catalog)
    assert "SIDEBOARD_SIZE" in codes(result)
    assert not result.legal


def test_a_profile_without_advisories_emits_none(legal_deck, bound_rules, catalog):
    deck = legal_deck.with_meta(sideboard={"filler-10": 3})
    assert validate(deck, rules=bound_rules, catalog=catalog).notices == ()


def test_the_shipped_profile_allows_ten_and_advises_eight(catalog):
    """What the field plays, with the caution the rulebook may still want."""
    from pathlib import Path

    from riftbound.domain.rules import load_format_rules

    profile = load_format_rules(Path("data/rules/constructed.json"))
    assert profile.int_constraint("sideboard_max") == 10
    advisory = profile.advisory("sideboard_max")
    assert advisory is not None
    assert advisory["recommended_max"] == 8
