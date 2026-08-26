"""Bans are reported, not silently applied.

The design point: we do not know which format the player is sitting down to play. A
card constructed has banned is fine in a casual pod, a local format, or an older event,
so removing it quietly -- or keeping it quietly -- is the app deciding something it has
no standing to decide. It tells; the player chooses.
"""

from __future__ import annotations

from riftbound.domain.bans import (
    SOURCE_PROFILE,
    SOURCE_UPSTREAM,
    drift,
    notices_for,
)
from riftbound.domain.deck import Deck

LEGEND = "vi-piltover-enforcer"


def a_deck(**overrides) -> Deck:
    main = {"vi-destructive": 3, "brazen-buccaneer": 3, "harpoon-squad": 3,
            "singular-relic": 1, "showcase-only": 3}
    main.update({f"filler-{i:02d}": 3 for i in range(1, 10)})
    main.update(overrides.pop("main", {}))
    return Deck.make(
        legend_id=LEGEND, champion_id="vi-destructive", main=main,
        runes={"fury-rune": 12},
        battlefields=["the-arena", "the-forge", "the-spire"],
        **overrides,
    )


def test_a_clean_deck_says_nothing(catalog, bound_rules):
    """No notice is a real answer, and the common one. Do not manufacture noise."""
    assert notices_for(a_deck(), rules=bound_rules, catalog=catalog) == ()


def test_a_banned_card_in_the_deck_is_reported(catalog, bound_rules):
    deck = a_deck(main={"banned-blade": 1})
    notices = notices_for(deck, rules=bound_rules, catalog=catalog)
    assert [n.card_id for n in notices] == ["banned-blade"]
    notice = notices[0]
    assert notice.source == SOURCE_PROFILE
    assert notice.enforced and notice.in_deck
    assert "not legal" in notice.describe("constructed")


def test_a_card_we_left_out_explains_itself(catalog, bound_rules):
    """Why our version differs from the tournament list it came from.

    Without this the player compares the two, sees a slot changed, and concludes the
    wizard made a mistake -- when in fact it declined to build with a banned card.
    """
    notices = notices_for(
        a_deck(), rules=bound_rules, catalog=catalog, considered=["banned-blade"]
    )
    assert len(notices) == 1
    assert not notices[0].in_deck
    message = notices[0].describe("constructed")
    assert "left out" in message
    assert "another format" in message, "it must not read as a refusal"


def test_the_card_data_and_our_profile_can_disagree(catalog, bound_rules, monkeypatch):
    """An upstream flag names no format, so it is reported and not enforced."""
    card = catalog.get("harpoon-squad")
    object.__setattr__(card, "banned_upstream", True)
    try:
        notices = notices_for(a_deck(), rules=bound_rules, catalog=catalog)
        assert [n.card_id for n in notices] == ["harpoon-squad"]
        assert notices[0].source == SOURCE_UPSTREAM
        assert not notices[0].enforced, "we did not act on this, and must not imply we did"
        assert "check your event" in notices[0].describe("constructed")
    finally:
        object.__setattr__(card, "banned_upstream", False)


def test_what_we_enforce_is_listed_first(catalog, bound_rules):
    """If a player reads one line, it should be the one that makes a deck illegal."""
    card = catalog.get("harpoon-squad")
    object.__setattr__(card, "banned_upstream", True)
    try:
        deck = a_deck(main={"banned-blade": 1})
        notices = notices_for(deck, rules=bound_rules, catalog=catalog)
        assert [n.card_id for n in notices] == ["banned-blade", "harpoon-squad"]
    finally:
        object.__setattr__(card, "banned_upstream", False)


def test_a_card_is_reported_once(catalog, bound_rules):
    """In the deck and in the list we considered is still one card."""
    deck = a_deck(main={"banned-blade": 1})
    notices = notices_for(
        deck, rules=bound_rules, catalog=catalog, considered=["banned-blade"]
    )
    assert len(notices) == 1
    assert notices[0].in_deck, "being in the deck is the more important of the two"


def test_drift_is_reported_rather_than_resolved(catalog, bound_rules):
    """A standing disagreement should be visible, not quietly settled either way."""
    assert drift(catalog, bound_rules) == ()
    card = catalog.get("harpoon-squad")
    object.__setattr__(card, "banned_upstream", True)
    try:
        assert drift(catalog, bound_rules) == ("harpoon-squad",)
    finally:
        object.__setattr__(card, "banned_upstream", False)
