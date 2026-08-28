"""Feasibility and construction.

These are the acceptance criterion. If :func:`assess` says a legal deck is possible then
:func:`build` must produce one, and it must survive the real validator — not a
re-implementation of the rules living in the test.
"""

from __future__ import annotations

from riftbound.domain.deck_builder import (
    REQ_BATTLEFIELDS,
    REQ_CHAMPION,
    REQ_LEGEND,
    REQ_MAIN,
    REQ_RUNES,
    Preference,
    assess,
    build,
    copy_cap,
    legal_champions,
    legal_main_pool,
)
from riftbound.domain.validator import validate

LEGEND = "vi-piltover-enforcer"


def full_collection(catalog, copies: int = 3) -> dict[str, int]:
    """Owns plenty of everything — the easy case."""
    owned = {c.card_id: copies for c in catalog}
    owned["fury-rune"] = 12
    owned["calm-rune"] = 12
    return owned


def minimal_collection(catalog) -> dict[str, int]:
    """Exactly enough for one legal deck and not one card more.

    13 main-deck cards at three copies each is 39, plus a single unique makes 40.
    """
    owned = {
        LEGEND: 1,
        "vi-destructive": 3,        # the champion, and part of the 40
        "brazen-buccaneer": 3,
        "harpoon-squad": 3,
        "showcase-only": 3,
        "singular-relic": 1,        # unique: one copy is the cap
        "fury-rune": 12,
        "the-arena": 1,
        "the-forge": 1,
        "the-spire": 1,
    }
    owned.update({f"filler-{i:02d}": 3 for i in range(1, 10)})   # 27
    return owned                                                  # 3+3+3+3+1+27 = 40


# -- the pools ----------------------------------------------------------------


def test_the_legal_pool_respects_domain_identity(catalog, bound_rules):
    legend = catalog.get(LEGEND)
    ids = {c.card_id for c in legal_main_pool(legend, catalog=catalog, rules=bound_rules)}
    assert "brazen-buccaneer" in ids
    assert "calm-intruder" not in ids, "outside a Fury legend's identity"


def test_the_legal_pool_excludes_banned_cards(catalog, bound_rules):
    legend = catalog.get(LEGEND)
    ids = {c.card_id for c in legal_main_pool(legend, catalog=catalog, rules=bound_rules)}
    assert "banned-blade" not in ids


def test_champions_must_share_a_tag_with_the_legend(catalog, bound_rules):
    legend = catalog.get(LEGEND)
    ids = {c.card_id for c in legal_champions(legend, catalog=catalog, rules=bound_rules)}
    assert ids == {"vi-destructive"}


# -- feasibility --------------------------------------------------------------


def test_a_full_collection_is_feasible(catalog, bound_rules):
    result = assess(LEGEND, full_collection(catalog), catalog=catalog, rules=bound_rules)
    assert result.ok, result.describe()
    assert result.blocking == ()


def test_an_empty_collection_is_not(catalog, bound_rules):
    result = assess(LEGEND, {}, catalog=catalog, rules=bound_rules)
    assert not result.ok
    assert {r.name for r in result.blocking} == {
        REQ_LEGEND, REQ_CHAMPION, REQ_MAIN, REQ_RUNES, REQ_BATTLEFIELDS
    }


def test_it_names_the_binding_requirement(catalog, bound_rules):
    """Saying *which* wall you hit is what lets the wizard ask a good question."""
    owned = full_collection(catalog)
    owned["fury-rune"] = 5                       # only 5 of the 12 runes
    result = assess(LEGEND, owned, catalog=catalog, rules=bound_rules)
    assert not result.ok
    assert [r.name for r in result.blocking] == [REQ_RUNES]
    runes = result.requirement(REQ_RUNES)
    assert runes.needed == 12 and runes.available == 5 and runes.short_by == 7
    assert "7 more runes" in result.describe()


def test_owning_no_legend_blocks_everything_else_being_fine(catalog, bound_rules):
    owned = full_collection(catalog)
    del owned[LEGEND]
    result = assess(LEGEND, owned, catalog=catalog, rules=bound_rules)
    assert [r.name for r in result.blocking] == [REQ_LEGEND]


def test_a_champion_you_do_not_own_blocks_the_deck(catalog, bound_rules):
    owned = full_collection(catalog)
    del owned["vi-destructive"]
    result = assess(LEGEND, owned, catalog=catalog, rules=bound_rules)
    assert [r.name for r in result.blocking] == [REQ_CHAMPION]


def test_battlefields_must_be_three_different_cards(catalog, bound_rules):
    """Owning nine copies of one battlefield is still only one battlefield."""
    owned = full_collection(catalog)
    for bf in ("the-forge", "the-spire"):
        del owned[bf]
    owned["the-arena"] = 9
    result = assess(LEGEND, owned, catalog=catalog, rules=bound_rules)
    assert [r.name for r in result.blocking] == [REQ_BATTLEFIELDS]
    assert result.requirement(REQ_BATTLEFIELDS).available == 1


def test_copies_beyond_the_limit_do_not_count_toward_capacity(catalog, bound_rules):
    """Ten copies of one card is still only three playable ones."""
    owned = {LEGEND: 1, "vi-destructive": 3, "fury-rune": 12,
             "the-arena": 1, "the-forge": 1, "the-spire": 1, "brazen-buccaneer": 99}
    result = assess(LEGEND, owned, catalog=catalog, rules=bound_rules)
    assert result.requirement(REQ_MAIN).available == 6, "3 champion + 3 buccaneer"


def test_a_unique_card_counts_once(catalog, bound_rules):
    owned = {LEGEND: 1, "singular-relic": 5}
    result = assess(LEGEND, owned, catalog=catalog, rules=bound_rules)
    assert result.requirement(REQ_MAIN).available == 1


def test_a_pool_of_signatures_cannot_fill_a_deck(catalog, bound_rules):
    """The signature cap binds as a group, so raw copy count overstates capacity."""
    from tests.conftest import make_card

    from riftbound.domain.cards import build_catalog

    signatures = [
        make_card(f"sig-{i:02d}", f"Sig {i:02d}", super_type="Signature", domains=("Fury",))
        for i in range(20)
    ]
    wider = build_catalog(list(catalog) + signatures)
    owned = {LEGEND: 1, **{c.card_id: 3 for c in signatures}}
    result = assess(LEGEND, owned, catalog=wider, rules=bound_rules)
    # 60 raw copies, but the profile allows only 3 signature cards in total.
    assert result.requirement(REQ_MAIN).available == 3


# -- construction -------------------------------------------------------------


def test_a_built_deck_passes_the_real_validator(catalog, bound_rules):
    """The whole contract in one line: if we build it, it is legal."""
    deck = build(LEGEND, full_collection(catalog), catalog=catalog, rules=bound_rules)
    assert deck is not None
    result = validate(deck, rules=bound_rules, catalog=catalog)
    assert result.legal, [i.message for i in result.errors]


def test_it_builds_from_the_bare_minimum(catalog, bound_rules):
    """Exactly 40 playable copies and nothing spare — the acceptance criterion."""
    owned = minimal_collection(catalog)
    assert assess(LEGEND, owned, catalog=catalog, rules=bound_rules).ok
    deck = build(LEGEND, owned, catalog=catalog, rules=bound_rules)
    assert deck is not None
    assert validate(deck, rules=bound_rules, catalog=catalog).legal


def test_a_built_deck_never_uses_more_than_you_own(catalog, bound_rules):
    owned = minimal_collection(catalog)
    deck = build(LEGEND, owned, catalog=catalog, rules=bound_rules)
    used: dict[str, int] = dict(deck.main)
    for card_id, qty in deck.runes.items():
        used[card_id] = used.get(card_id, 0) + qty
    for card_id in deck.battlefields:
        used[card_id] = used.get(card_id, 0) + 1
    for card_id, qty in used.items():
        assert qty <= owned.get(card_id, 0), f"used {qty} of {card_id}, owns {owned.get(card_id, 0)}"


def test_partial_ownership_is_used_up_to_what_you_have(catalog, bound_rules):
    """Owning two of a three-of contributes two, not zero and not three."""
    owned = full_collection(catalog)
    owned["brazen-buccaneer"] = 2
    deck = build(LEGEND, owned, catalog=catalog, rules=bound_rules)
    assert deck.main.get("brazen-buccaneer", 0) <= 2
    assert validate(deck, rules=bound_rules, catalog=catalog).legal


def test_it_returns_nothing_when_no_legal_deck_exists(catalog, bound_rules):
    assert build(LEGEND, {}, catalog=catalog, rules=bound_rules) is None


def test_assess_and_build_always_agree(catalog, bound_rules):
    """If assess says yes, build must deliver. That is the guarantee.

    Sweeps collections from empty to full, one card at a time, so the boundary between
    infeasible and feasible is crossed in both directions.
    """
    everything = sorted(full_collection(catalog).items())
    owned: dict[str, int] = {}
    for card_id, copies in everything:
        owned[card_id] = copies
        feasible = assess(LEGEND, owned, catalog=catalog, rules=bound_rules).ok
        deck = build(LEGEND, owned, catalog=catalog, rules=bound_rules)
        assert feasible == (deck is not None), f"disagreed after adding {card_id}"
        if deck is not None:
            assert validate(deck, rules=bound_rules, catalog=catalog).legal


# -- preference ---------------------------------------------------------------


def test_preference_decides_which_cards_get_played(catalog, bound_rules):
    """With more cards than slots, the meta's favourites should win."""
    owned = full_collection(catalog)
    liked = Preference(play_rate={"filler-01": 1.0, "filler-02": 0.9}, copies={})
    deck = build(LEGEND, owned, catalog=catalog, rules=bound_rules, preference=liked)
    assert deck.main.get("filler-01") == 3
    assert deck.main.get("filler-02") == 3


def test_preference_decides_how_many_copies(catalog, bound_rules):
    """The field runs one of some cards and three of others; copy counts say which."""
    owned = full_collection(catalog)
    pref = Preference(
        play_rate={"filler-01": 1.0, "filler-02": 0.9},
        copies={"filler-01": 1, "filler-02": 3},
    )
    deck = build(LEGEND, owned, catalog=catalog, rules=bound_rules, preference=pref)
    assert deck.main["filler-02"] == 3
    # filler-01 is wanted as a one-of, and is only topped up if the deck runs short.
    assert deck.main["filler-01"] >= 1


def test_the_champion_is_always_in_the_main_deck(catalog, bound_rules):
    """Nominating a champion that is not in the deck is illegal, so build cannot do it."""
    owned = full_collection(catalog)
    deck = build(LEGEND, owned, catalog=catalog, rules=bound_rules)
    assert deck.champion_id
    assert deck.champion_id in deck.main


def test_builds_are_reproducible(catalog, bound_rules):
    owned = full_collection(catalog)
    first = build(LEGEND, owned, catalog=catalog, rules=bound_rules)
    second = build(LEGEND, owned, catalog=catalog, rules=bound_rules)
    assert first == second


def test_an_unknown_legend_is_reported_not_raised(catalog, bound_rules):
    result = assess("no-such-legend", {}, catalog=catalog, rules=bound_rules)
    assert not result.ok
    assert "not in the card data" in result.requirement(REQ_LEGEND).detail
    assert build("no-such-legend", {}, catalog=catalog, rules=bound_rules) is None


def test_a_swarm_card_can_fill_more_than_three_slots(catalog, bound_rules):
    """If the card's text lifts the limit, the builder must be able to use it.

    Capping at three would make a whole archetype unbuildable: the wizard would tell a
    player holding twenty Spiderlings that they cannot build the deck they own.
    """
    swarm = catalog.get("brazen-buccaneer")
    object.__setattr__(swarm, "unlimited_copies", True)
    try:
        assert copy_cap(swarm, rules=bound_rules) > 3
    finally:
        object.__setattr__(swarm, "unlimited_copies", False)
    assert copy_cap(swarm, rules=bound_rules) == 3


# -- runes have to be able to cast the deck -------------------------------------


def test_the_rune_base_covers_the_hungriest_card_of_each_domain(catalog, bound_rules):
    """Power is the domain-specific half of a cost; energy pays the rest and is
    domain-free. So a card asking four Body power cannot be cast from three Body runes,
    however popular the other nine are.

    Runes used to be filled like any other flat zone -- most-played first, take as many
    as you own -- which handed a Mind deck twelve Body Runes. Across 105 built decks,
    only 57% had a base that could cast their own cards.
    """
    from riftbound.domain.deck_builder import power_floor

    main = {"vi-destructive": 3, "calm-intruder": 3}
    floor = power_floor(main, catalog)
    # Whatever the catalogue says, the floor never exceeds a card's own demand and
    # never misses a domain that demands any.
    for card_id in main:
        card = catalog.get(card_id)
        if card and card.power and len(card.domains) == 1:
            assert floor.get(card.domains[0], 0) >= card.power


def test_a_card_in_two_domains_sets_no_floor(catalog):
    """Its power can be paid from either, so on its own it constrains neither. It still
    weighs on the proportional remainder."""
    from conftest import make_card
    from riftbound.domain.cards import build_catalog
    from riftbound.domain.deck_builder import power_floor

    split = build_catalog([make_card("dual", "Dual", domains=("Fury", "Calm"), power=3)])
    assert power_floor({"dual": 3}, split) == {}


def test_power_beats_popularity_when_the_two_disagree(catalog, bound_rules):
    """The bug, in one deck: a Mind card in a field that mostly plays Body."""
    from conftest import make_card
    from riftbound.domain.cards import build_catalog
    from riftbound.domain.deck_builder import Preference, _fill_runes

    cards = [
        make_card("body-rune", "Body Rune", card_type="Rune", super_type="Basic",
                  domains=("Body",), cost=None, might=None, power=0),
        make_card("mind-rune", "Mind Rune", card_type="Rune", super_type="Basic",
                  domains=("Mind",), cost=None, might=None, power=0),
        make_card("mind-bomb", "Mind Bomb", domains=("Mind",), cost=5, power=4),
    ]
    cat = build_catalog(cards)
    pool = [cat.get("body-rune"), cat.get("mind-rune")]
    owned = {"body-rune": 12, "mind-rune": 12}
    # The field adores Body Runes and has barely seen a Mind Rune.
    pref = Preference(play_rate={"body-rune": 1.0, "mind-rune": 0.01}, copies={})

    runes = _fill_runes(pool, {"mind-bomb": 3}, owned, 12, pref, cat)
    assert runes.get("mind-rune", 0) >= 4, (
        "the deck cannot be cast without four Mind runes, whatever the field prefers"
    )
    assert sum(runes.values()) == 12
