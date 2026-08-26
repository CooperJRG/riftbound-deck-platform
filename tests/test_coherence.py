"""A deck is not forty individually popular cards.

The failure this guards against, in the user's own terms: a deck wants Dazzling Aurora
*and* Elder Dragon. The player owns no Auroras. Filling that hole card by card keeps the
expensive units and throws away the thing that was buying them time -- so the player
ends up with a deck of costly cards and no plan, assembled by a tool that never asked
whether the plan still worked.

Two mechanisms answer it, and both are tested here:

* **pairing** -- each card is chosen against what is already in the deck rather than
  against the format in general, so an enabler and its payoff travel together;
* **archetype selection** -- when the core of one family is out of reach, the strongest
  family the collection *can* field is preferred over patching one it cannot.
"""

from __future__ import annotations

import pytest

from riftbound.domain.deck_builder import Preference, build
from riftbound.domain.legend_index import Cluster, LegendProfile, build_profile
from riftbound.domain.meta import MetaDeck, Provenance
from riftbound.domain.deck import Deck

LEGEND = "vi-piltover-enforcer"
CHAMPION = "vi-destructive"

#: The enabler, and the expensive payoff that only makes sense alongside it.
ENABLER = "brazen-buccaneer"
PAYOFF = "harpoon-squad"
#: A card of the same domain that stands on its own. Same domain matters: a card the
#: legend cannot legally play would never be chosen for reasons that have nothing to do
#: with coherence, and the test would pass or fail for the wrong reason.
STANDALONE = "showcase-only"


def a_meta_deck(main: dict[str, int], deck_id: str) -> MetaDeck:
    filled = dict(main)
    total = sum(filled.values())
    for i in range(1, 15):
        if total >= 40:
            break
        card_id = f"filler-{i:02d}"
        take = min(3, 40 - total)
        filled[card_id] = filled.get(card_id, 0) + take
        total += take
    return MetaDeck(
        deck=Deck.make(
            legend_id=LEGEND, champion_id=CHAMPION, main=filled,
            runes={"fury-rune": 12},
            battlefields=["the-arena", "the-forge", "the-spire"],
        ),
        provenance=Provenance(source="t", source_slug=deck_id, url=""),
    )


@pytest.fixture()
def paired_profile() -> LegendProfile:
    """A meta where the enabler and the payoff are always played together."""
    decks = [
        a_meta_deck({CHAMPION: 3, ENABLER: 3, PAYOFF: 3}, f"pair-{i}") for i in range(6)
    ]
    # ...and a second, equally common plan that plays neither.
    decks += [
        a_meta_deck({CHAMPION: 3, STANDALONE: 3, "singular-relic": 1}, f"solo-{i}")
        for i in range(6)
    ]
    scores = {d.deck_id: 1.0 for d in decks}
    return build_profile(LEGEND, decks, scores)


# -- the pairing signal -------------------------------------------------------


def test_pair_strength_is_a_conditional_probability(paired_profile):
    """Always played together means 1.0; never together means 0."""
    assert paired_profile.pair_strength(PAYOFF, ENABLER) == pytest.approx(1.0)
    assert paired_profile.pair_strength(PAYOFF, STANDALONE) == 0.0


def test_pair_strength_of_an_unknown_card_is_zero_not_an_error(paired_profile):
    assert paired_profile.pair_strength("nobody-plays-this", ENABLER) == 0.0
    assert paired_profile.pair_strength(PAYOFF, "nobody-plays-this") == 0.0


def test_a_build_without_the_pairing_signal_still_works(catalog, bound_rules, paired_profile):
    """Coherence is a preference. It must never be the reason a deck cannot be built."""
    owned = {c.card_id: 3 for c in catalog}
    owned["fury-rune"] = 12
    static = Preference(play_rate=paired_profile.play_rate, copies=paired_profile.copies)
    assert build(LEGEND, owned, catalog=catalog, rules=bound_rules, preference=static)


def test_the_payoff_is_dropped_when_its_enabler_is_not_owned(
    catalog, bound_rules, paired_profile
):
    """The reported case, stated directly.

    Both plans are equally popular, so popularity alone cannot separate them. Without
    the enabler the deck should move to the plan that does not need it, rather than
    keeping the expensive half of a plan it can no longer execute.
    """
    owned = {c.card_id: 3 for c in catalog}
    owned["fury-rune"] = 12
    owned[ENABLER] = 0  # the Auroras they do not have

    deck = build(
        LEGEND, owned, catalog=catalog, rules=bound_rules,
        preference=paired_profile.preference(),
    )
    assert deck is not None
    assert deck.main.get(STANDALONE, 0) > 0, "the plan that survives should be preferred"
    assert deck.main.get(PAYOFF, 0) < deck.main.get(STANDALONE, 0), (
        "an expensive payoff should not outrank a card that still works"
    )


def test_the_payoff_is_kept_when_the_enabler_is_there(catalog, bound_rules, paired_profile):
    """The other half of the same rule: a plan that can be executed should be."""
    owned = {c.card_id: 3 for c in catalog}
    owned["fury-rune"] = 12
    owned[STANDALONE] = 0

    deck = build(
        LEGEND, owned, catalog=catalog, rules=bound_rules,
        preference=paired_profile.preference(),
    )
    assert deck is not None
    assert deck.main.get(ENABLER, 0) > 0
    assert deck.main.get(PAYOFF, 0) > 0, "with the enabler present, the payoff belongs"


# -- archetype coverage -------------------------------------------------------


def test_coverage_gives_partial_credit(paired_profile):
    """Two of a three-of is most of the way there, and scoring it zero would discard a
    deck the player can very nearly field."""
    cluster = Cluster(
        cluster_id="c", deck_ids=("pair-0",), core=frozenset({ENABLER}),
        flex=frozenset(), score=1.0,
    )
    assert paired_profile.coverage(cluster, {ENABLER: 3}) == pytest.approx(1.0)
    assert paired_profile.coverage(cluster, {ENABLER: 2}) == pytest.approx(2 / 3)
    assert paired_profile.coverage(cluster, {}) == 0.0


def test_coverage_of_a_coreless_cluster_is_zero_not_a_crash(paired_profile):
    empty = Cluster(cluster_id="c", deck_ids=(), core=frozenset(), flex=frozenset(), score=1.0)
    assert paired_profile.coverage(empty, {ENABLER: 3}) == 0.0


def test_the_strongest_fieldable_archetype_is_chosen(paired_profile):
    """Strength still counts, but not on its own.

    Owning none of the enabler a plan is built around does not mean playing that plan
    without it; it means playing a different plan.
    """
    chosen = paired_profile.best_cluster({STANDALONE: 3, CHAMPION: 3})
    assert chosen is not None
    assert ENABLER not in chosen.core, "picked a family whose core they cannot field"


def test_best_cluster_survives_an_empty_collection(paired_profile):
    """Before anything is known we still need somewhere to start."""
    assert paired_profile.best_cluster({}) is not None


def test_a_minimum_can_rule_every_archetype_out(paired_profile):
    """Asking for a coverage nobody meets returns nothing rather than a bad guess."""
    assert paired_profile.best_cluster({}, minimum=0.5) is None
