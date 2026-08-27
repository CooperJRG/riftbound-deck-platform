"""Two scores, and the choice the wizard makes with them.

The wizard hands over decks from three places -- a published list, that list repaired
against a collection, and a build from the collection alone -- and only the first ever
had a score. `meta_scoring.score_deck` reads pedigree, which a repair does not have: the
moment a card is swapped it stops being the list that placed 3rd of 257.

So both scores are computed from contents, and differ only in what they are measured
against. What is pinned here:

* the strongest published deck for a champion is 100 on the champion scale, by
  construction -- that is the definition, not an emergent property;
* the two scales genuinely disagree, which is the reason for showing both;
* a champion with no published lists is *unscored*, never zero;
* the choice between two repairs is made on the champion scale, because a repair
  competes with other builds of the same deck and not with the format.
"""

from __future__ import annotations

import pytest

from conftest import make_card
from riftbound.domain.cards import build_catalog
from riftbound.domain.deck import Deck
from riftbound.domain.meta import EVIDENCE_TOURNAMENT_PLACED, MetaDeck, Provenance
from riftbound.domain.smart_decks.scoring import (
    UNSCORED,
    DeckScore,
    Reference,
    better,
    build_scoreboard,
    choose,
    coverage_of,
)

LEGEND = "vi-piltover-enforcer"
STRONG = "vi-destructive"        # champion of the dominant archetype
FRINGE = "vi-peacekeeper"        # champion nobody much plays
STAPLES = [f"staple-{i:02d}" for i in range(1, 14)]
NICHE = [f"niche-{i:02d}" for i in range(1, 14)]

CATALOG = build_catalog(
    [
        make_card(LEGEND, "Vi - Piltover Enforcer", card_type="Legend", cost=None, might=None),
        make_card(STRONG, "Vi - Destructive", super_type="Champion"),
        make_card(FRINGE, "Vi - Peacekeeper", super_type="Champion"),
        *[make_card(c, c.title()) for c in STAPLES],
        *[make_card(c, c.title()) for c in NICHE],
    ]
)


def a_deck(champion: str, cards: list[str], *, copies: int = 3) -> Deck:
    main = {champion: 3}
    main.update({c: copies for c in cards})
    return Deck.make(name="d", legend_id=LEGEND, champion_id=champion, main=main)


def a_meta_deck(champion: str, cards: list[str], index: int = 0) -> MetaDeck:
    return MetaDeck(
        deck=a_deck(champion, cards),
        provenance=Provenance(
            source="t", source_slug=f"{champion}-{index}", url="",
            evidence=EVIDENCE_TOURNAMENT_PLACED, tournament_date="2026-06-01",
        ),
    )


def a_field() -> list[MetaDeck]:
    """A dominant champion on the staples, and a fringe one on cards nobody else plays."""
    return [
        *[a_meta_deck(STRONG, STAPLES, i) for i in range(9)],
        *[a_meta_deck(FRINGE, NICHE, i) for i in range(2)],
    ]


def a_board(scores=None):
    field = a_field()
    if scores is None:
        # The dominant champion's lists are the better-regarded ones.
        scores = {
            d.deck_id: (0.9 if d.deck.champion_id == STRONG else 0.4) for d in field
        }
    return build_scoreboard(field, scores)


# -- the scales ----------------------------------------------------------------


def test_the_strongest_deck_for_a_champion_scores_one_hundred():
    """The definition, not an emergent property: this is what the number means."""
    board = a_board()
    assert board.score(a_deck(STRONG, STAPLES)).champion == pytest.approx(100.0)
    assert board.score(a_deck(FRINGE, NICHE)).champion == pytest.approx(100.0)


def test_the_two_scales_disagree_and_that_is_the_point():
    """A good build of a fringe champion is 100 for its champion and far less in the
    format. Collapsing them into one number hides whichever fact the player needed."""
    board = a_board()
    fringe = board.score(a_deck(FRINGE, NICHE))
    assert fringe.champion == pytest.approx(100.0)
    assert fringe.meta < 60, "a champion the meta thinks little of must not read as a staple"

    dominant = board.score(a_deck(STRONG, STAPLES))
    assert dominant.meta == pytest.approx(100.0)


def test_a_repair_can_never_out_score_the_list_it_repaired():
    """The property the first version of this module got backwards.

    It scored a deck by summing the format-wide play rate of its cards, so swapping any
    card for a more-played one always raised the number -- which is what a repair does by
    construction. Every repair scored at or above the deck it came from, and the wizard
    reported a compromise as an improvement. Coverage is bounded by 1, so the best a deck
    can do is *be* the reference.
    """
    board = a_board()
    original = a_deck(STRONG, STAPLES)
    assert board.score(original).champion == pytest.approx(100.0)

    # Swap three of the archetype's cards for the most-played cards in the format.
    repaired = a_deck(STRONG, STAPLES[3:])
    for card in NICHE[:3]:
        repaired.main[card] = 3
    score = board.score(repaired)
    assert score.champion < 100.0, "a repair must not beat the list it repaired"
    assert score.coverage < 1.0


def test_stacking_popular_cards_does_not_raise_the_score():
    """Nine copies of a staple is not three times the deck."""
    board = a_board()
    honest = a_deck(STRONG, STAPLES)
    stacked = a_deck(STRONG, STAPLES, copies=9)
    assert board.score(stacked).champion <= board.score(honest).champion


def test_a_champion_with_one_published_list_is_not_a_low_bar():
    """The second fault: dividing by the best play-rate mass among a champion's decks
    made a single-deck champion trivially clearable. Measuring against a real forty-card
    list means only an exact copy reaches 100."""
    field = [*a_field(), a_meta_deck(FRINGE, NICHE, 99)]
    board = build_scoreboard(field, {d.deck_id: 0.5 for d in field})
    partial = a_deck(FRINGE, NICHE[:7])
    assert board.score(partial).champion < 100.0
    assert board.score(a_deck(FRINGE, NICHE)).champion == pytest.approx(100.0)


def test_coverage_is_capped_per_card():
    reference = Reference(deck_id="r", main={"a": 3, "b": 3}, copies=6, score=1.0)
    plenty = Deck.make(name="d", legend_id=LEGEND, champion_id=STRONG, main={"a": 9})
    assert coverage_of(plenty, reference) == pytest.approx(0.5)


def test_a_champion_with_no_published_lists_is_unscored_not_zero():
    """A champion nobody has published is not a champion that scores badly."""
    board = a_board()
    score = board.score(a_deck("nobody-plays-this", STAPLES))
    assert score.champion == UNSCORED
    assert score.scored is False
    assert "no published lists" in score.describe()


def test_an_empty_field_scores_nothing_rather_than_dividing_by_zero():
    board = build_scoreboard([], {})
    score = board.score(a_deck(STRONG, STAPLES))
    assert score.meta == UNSCORED
    assert score.champion == UNSCORED
    assert score.scored is False


# -- the choice ----------------------------------------------------------------


def test_the_choice_is_made_on_the_champion_scale():
    """A repair competes with other builds of the same deck, not with the format.

    Measuring it against the format's best would let a swap that is clearly right for a
    fringe champion lose on the strength of a denominator neither deck can influence.
    """
    board = a_board()
    # Two repairs of the fringe deck. The fuller one keeps more of the real list, and
    # both are far below the format's best.
    conservative = a_deck(FRINGE, NICHE[:6])
    free = a_deck(FRINGE, NICHE)
    assert board.score(free).meta < 60, "both are modest in the format"
    assert choose([("conservative", conservative), ("free", free)], board) == "free"


def test_a_missing_option_never_wins():
    board = a_board()
    assert choose([("conservative", None), ("free", a_deck(STRONG, STAPLES))], board) == "free"
    assert choose([("conservative", None), ("free", None)], board) == ""


def test_a_scored_deck_beats_an_unscored_one():
    scored = DeckScore(meta=10.0, champion=10.0, coverage=0.1)
    unscored = DeckScore(meta=UNSCORED, champion=UNSCORED, coverage=0.9)
    assert better(scored, unscored)
    assert not better(unscored, scored)


def test_an_exact_tie_falls_back_to_coverage_rather_than_argument_order():
    left = DeckScore(meta=50.0, champion=50.0, coverage=0.8)
    right = DeckScore(meta=50.0, champion=50.0, coverage=0.4)
    assert better(left, right)
    assert not better(right, left)
