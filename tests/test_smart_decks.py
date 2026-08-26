"""The Smart Decks session engine.

The subtle parts are the knowledge semantics — what an answer actually tells us — and
they are where the real bug lived. See
:func:`test_saying_you_have_all_of_them_does_not_cap_your_collection`.
"""

from __future__ import annotations

import random

import pytest

from riftbound.domain.deck import Deck
from riftbound.domain.deck_builder import (
    legal_main_pool,
    legal_zone_pool,
)
from riftbound.domain.legend_index import build_index, build_profile
from riftbound.domain.meta import MetaDeck, Provenance
from riftbound.domain.smart_decks import (
    PHASE_CHECKLIST,
    PHASE_DONE,
    PHASE_PROPOSE,
    Engine,
    Knowledge,
    deck_requirements,
    gaps_for,
    repair,
    run_to_completion,
    unknown_cards,
)
from riftbound.domain.smart_decks_harness import (
    Player,
    random_collection,
    simulate,
)
from riftbound.domain.validator import validate

LEGEND = "vi-piltover-enforcer"


def a_deck(main: dict[str, int] | None = None, **kw) -> Deck:
    base = {"vi-destructive": 3, "brazen-buccaneer": 3, "harpoon-squad": 3,
            "singular-relic": 1, "showcase-only": 3}
    base.update({f"filler-{i:02d}": 3 for i in range(1, 10)})
    return Deck.make(
        legend_id=LEGEND, champion_id="vi-destructive",
        main=main if main is not None else base,
        runes=kw.get("runes", {"fury-rune": 12}),
        battlefields=kw.get("battlefields", ["the-arena", "the-forge", "the-spire"]),
    )


def as_meta(deck: Deck, deck_id: str) -> MetaDeck:
    return MetaDeck(deck=deck, provenance=Provenance(source="t", source_slug=deck_id, url=""))


def full_owned(catalog) -> dict[str, int]:
    owned = {c.card_id: 3 for c in catalog}
    owned["fury-rune"] = 12
    return owned


def known(owned: dict[str, int]) -> Knowledge:
    """A fully surveyed collection, where a zero means *known to own none*.

    Deliberately not :meth:`Knowledge.from_collection`, which drops zeros: a card absent
    from a collection file is unrecorded, not known-absent, and the repair tests below
    mean the second thing.
    """
    return Knowledge(exact=dict(owned))


# -- knowledge ----------------------------------------------------------------


def test_a_shortfall_is_recorded_exactly():
    """"I have 2 of the 3" is the true number, so we know it."""
    knowledge = Knowledge().with_answer({"a": 3}, {"a": 2})
    assert knowledge.is_exact("a")
    assert knowledge.lower_bound("a") == 2


def test_saying_you_have_all_of_them_does_not_cap_your_collection():
    """The bug this test exists for.

    A deck screen says "Need 6 — you have [0..6]", so "all of them" means *at least*
    six, never exactly six. Recording it as exact capped every collection at whatever
    the first deck happened to ask for: a player holding twelve Calm Runes was written
    down as having six, then told they were one rune short of a deck they could build.
    """
    knowledge = Knowledge().with_answer({"fury-rune": 6}, {"fury-rune": 6})
    assert knowledge.lower_bound("fury-rune") == 6
    assert not knowledge.is_exact("fury-rune"), "they may well own more"
    assert knowledge.is_known("fury-rune")


def test_an_untouched_card_is_a_lower_bound_not_a_guess():
    """A card left alone means they have what the deck asked for, at least."""
    knowledge = Knowledge().with_answer({"a": 3, "b": 3}, {"a": 1})
    assert knowledge.is_exact("a") and knowledge.lower_bound("a") == 1
    assert not knowledge.is_exact("b") and knowledge.lower_bound("b") == 3


def test_later_answers_refine_earlier_ones():
    knowledge = Knowledge().with_answer({"a": 3}, {}).with_answer({"a": 6}, {"a": 4})
    assert knowledge.is_exact("a")
    assert knowledge.lower_bound("a") == 4


def test_the_constructor_only_ever_sees_lower_bounds():
    """Anything built from this must be genuinely ownable."""
    knowledge = Knowledge(exact={"a": 2}, at_least={"b": 3})
    assert knowledge.owned() == {"a": 2, "b": 3}


def test_zero_copies_are_remembered_as_zero():
    knowledge = Knowledge().with_answer({"a": 3}, {"a": 0})
    assert knowledge.is_exact("a")
    assert "a" not in knowledge.owned()


def test_a_recorded_collection_is_exact_by_definition():
    knowledge = Knowledge.from_collection({"a": 2, "b": 0})
    assert knowledge.is_exact("a") and knowledge.lower_bound("a") == 2
    assert not knowledge.is_known("b")


# -- gaps ---------------------------------------------------------------------


def test_requirements_span_every_zone():
    required = deck_requirements(a_deck())
    assert required["fury-rune"] == 12
    assert required["the-arena"] == 1
    assert required[LEGEND] == 1


def test_gaps_are_measured_in_copies_not_cards():
    """Missing one of a three-of is a one-copy hole, not a lost slot."""
    knowledge = Knowledge(exact={"brazen-buccaneer": 2})
    gap = next(g for g in gaps_for(a_deck(), knowledge) if g.card_id == "brazen-buccaneer")
    assert gap.needed == 3 and gap.have == 2 and gap.short == 1


def test_unasked_cards_are_not_counted_as_gaps():
    """We have not asked, so we do not know — that is not the same as missing."""
    assert gaps_for(a_deck(), Knowledge()) == ()


def test_unknown_cards_are_reported_for_question_selection():
    knowledge = Knowledge(exact={"brazen-buccaneer": 3})
    unknown = unknown_cards(a_deck(), knowledge)
    assert "brazen-buccaneer" not in unknown
    assert "harpoon-squad" in unknown


# -- repair -------------------------------------------------------------------


@pytest.fixture()
def profile(catalog):
    decks = [as_meta(a_deck(), "d1"), as_meta(a_deck(), "d2")]
    return build_profile(LEGEND, decks, {"d1": 1.0, "d2": 0.9})


def test_a_deck_you_can_already_field_needs_no_repair(catalog, bound_rules, profile):
    fixed = repair(a_deck(), known(full_owned(catalog)), profile=profile, catalog=catalog,
                   rules=bound_rules, conservative=True)
    assert fixed is not None and fixed.drift == 0 and not fixed.changed


def test_a_repair_keeps_the_copies_you_do_own(catalog, bound_rules, profile):
    """Short one of a three-of: keep two and find one more elsewhere."""
    owned = full_owned(catalog)
    owned["brazen-buccaneer"] = 2
    fixed = repair(a_deck(), known(owned), profile=profile,
                   catalog=catalog, rules=bound_rules, conservative=False)
    assert fixed is not None
    assert fixed.deck.main.get("brazen-buccaneer") == 2
    assert fixed.drift == 1
    assert validate(fixed.deck, rules=bound_rules, catalog=catalog).legal


def test_a_repaired_deck_is_still_legal(catalog, bound_rules, profile):
    owned = full_owned(catalog)
    for card_id in ("brazen-buccaneer", "harpoon-squad"):
        owned[card_id] = 0
    fixed = repair(a_deck(), known(owned), profile=profile,
                   catalog=catalog, rules=bound_rules, conservative=False)
    assert fixed is not None
    assert validate(fixed.deck, rules=bound_rules, catalog=catalog).legal


def test_a_repair_says_what_it_changed(catalog, bound_rules, profile):
    """A player deserves to know they are holding a cousin of the deck, not the deck."""
    owned = full_owned(catalog)
    owned["brazen-buccaneer"] = 0
    fixed = repair(a_deck(), known(owned), profile=profile,
                   catalog=catalog, rules=bound_rules, conservative=False)
    assert fixed.swaps
    assert all(s.out_card_id == "brazen-buccaneer" for s in fixed.swaps)
    assert all(s.reason for s in fixed.swaps), "each swap explains itself"


def test_a_deck_too_far_out_of_reach_is_not_repaired(catalog, bound_rules, profile):
    """Better to move on than to hand back something unrecognisable."""
    owned = {c.card_id: 0 for c in catalog}
    owned.update({LEGEND: 1, "fury-rune": 12})
    knowledge = known(owned)
    assert repair(a_deck(), knowledge, profile=profile, catalog=catalog,
                  rules=bound_rules, conservative=False) is None


def test_a_legend_has_no_substitute(catalog, bound_rules, profile):
    """Every other hole can be filled; the legend defines the deck."""
    knowledge = known({**full_owned(catalog), LEGEND: 0})
    assert repair(a_deck(), knowledge, profile=profile, catalog=catalog,
                  rules=bound_rules, conservative=False) is None


# -- the session loop ---------------------------------------------------------


@pytest.fixture()
def engine(catalog, bound_rules, profile):
    decks = {"d1": as_meta(a_deck(), "d1"), "d2": as_meta(a_deck(), "d2")}
    return Engine(catalog=catalog, rules=bound_rules, profile=profile,
                  decks=decks, scores={"d1": 1.0, "d2": 0.9})


def test_the_first_question_is_the_best_deck(engine):
    """The opening impression should be a deck, not a checklist."""
    proposal = engine.propose(engine.start(LEGEND))
    assert proposal.phase == PHASE_PROPOSE
    assert proposal.deck.deck_id == "d1"
    assert proposal.floor is None


def test_an_answer_that_covers_everything_produces_a_floor_at_once(engine, catalog):
    session = engine.start(LEGEND)
    first = engine.propose(session)
    required = deck_requirements(first.deck.deck)
    session = engine.answer(session, "d1", dict(required))     # "I have all of it"
    assert engine.propose(session).floor is not None


def test_a_floor_can_only_improve(engine, catalog):
    """Once we can promise a deck, no later answer may take it away."""
    owned = full_owned(catalog)
    session = engine.start(LEGEND)
    seen_floor = False
    for _ in range(4):
        proposal = engine.propose(session)
        if proposal.floor is not None:
            seen_floor = True
        elif seen_floor:
            pytest.fail("the floor disappeared")
        if proposal.phase == PHASE_DONE:
            break
        if proposal.deck is not None:
            required = deck_requirements(proposal.deck.deck)
            session = engine.answer(
                session, proposal.deck.deck_id,
                {c: min(n, owned.get(c, 0)) for c, n in required.items()},
            )
        elif proposal.question:
            session = engine.answer_question(
                session, {c: owned.get(c, 0) for c in proposal.question.card_ids},
                proposal.question.card_ids,
            )
    assert seen_floor


def test_it_asks_directly_once_decks_stop_reaching_an_answer(engine, catalog):
    """A question aimed at the binding requirement beats another near-identical deck."""
    session = engine.start(LEGEND)
    first = engine.propose(session)
    # Owns almost nothing, so no deck will do.
    session = engine.answer(session, "d1", {c: 0 for c in deck_requirements(first.deck.deck)})
    second = engine.propose(session)
    assert second.phase == PHASE_CHECKLIST
    assert second.question is not None and second.question.card_ids


def test_a_direct_question_covers_every_blocking_requirement_at_once(engine, catalog):
    """Asking them one at a time cost a round each."""
    session = engine.start(LEGEND)
    first = engine.propose(session)
    required = deck_requirements(first.deck.deck)
    partial = {c: 0 for c in required}
    partial[LEGEND] = 1
    session = engine.answer(session, "d1", partial)
    question = engine.propose(session).question
    assert question is not None
    # One question, naming every wall they have hit — not one round per wall.
    assert "champion" in question.reason
    assert "cards" in question.reason
    assert "runes" in question.reason
    assert question.card_ids


def test_a_checklist_answer_is_exact_including_the_zeros(engine):
    session = engine.start(LEGEND)
    session = engine.answer_question(session, {"brazen-buccaneer": 0}, ["brazen-buccaneer"])
    assert session.knowledge.is_exact("brazen-buccaneer")


def test_a_session_with_everything_ends_with_a_legal_deck(engine, catalog, bound_rules):
    run = run_to_completion(engine, LEGEND, full_owned(catalog))
    assert run.floor is not None
    assert validate(run.floor, rules=bound_rules, catalog=catalog).legal
    assert run.rounds_to_answer is not None


def test_a_session_with_nothing_says_so_rather_than_inventing_a_deck(engine):
    run = run_to_completion(engine, LEGEND, {})
    assert run.floor is None
    assert run.proposal.phase == PHASE_DONE
    assert "Short by" in run.proposal.reason


# -- the acceptance criterion -------------------------------------------------


def test_the_acceptance_criterion_holds(catalog, bound_rules):
    """If a legal deck exists in the collection, the wizard finds one.

    A small deterministic run of the harness that guards the whole feature. The full
    sweep — 49 legends against 20 synthetic players, 980 sessions — is run out of band;
    this is the version cheap enough to keep in the suite.

    v2's equivalent feature recorded ``strictBuildableEmptyResultRate: 0.814``: it
    returned nothing four times in five, and nothing measured it.
    """
    decks = {"d1": as_meta(a_deck(), "d1"), "d2": as_meta(a_deck(), "d2")}
    index = build_index(decks.values(), {"d1": 1.0, "d2": 0.9})
    rng = random.Random(4)
    players = [
        Player(f"p{i}", random_collection(catalog, rng=rng, scale=scale))
        for i, scale in enumerate((1.0, 0.8, 0.6, 0.45, 0.3, 0.2))
    ]
    report = simulate(
        catalog=catalog, rules=bound_rules, index=index, decks=decks.values(),
        scores={"d1": 1.0, "d2": 0.9}, legends=[LEGEND], players=players,
    )
    assert report.solved_when_feasible == 1.0, report.render()
    assert report.false_negatives == 0, report.render()
    assert report.p90_rounds <= 5, report.render()


def test_every_deck_the_wizard_offers_is_legal(catalog, bound_rules):
    """Whatever route it took, what comes out must pass the real validator."""
    decks = {"d1": as_meta(a_deck(), "d1")}
    index = build_index(decks.values(), {"d1": 1.0})
    rng = random.Random(11)
    engine = Engine(
        catalog=catalog, rules=bound_rules, profile=index.get(LEGEND),
        decks=decks, scores={"d1": 1.0},
    )
    for scale in (1.0, 0.7, 0.5, 0.3):
        owned = random_collection(catalog, rng=rng, scale=scale)
        run = run_to_completion(engine, LEGEND, owned)
        if run.floor is None:
            continue
        result = validate(run.floor, rules=bound_rules, catalog=catalog)
        assert result.legal, [i.message for i in result.errors]
        for card_id, qty in run.floor.main.items():
            assert qty <= owned.get(card_id, 0), "built with cards they do not own"


# -- the closing question -----------------------------------------------------


@pytest.fixture()
def bare_engine(catalog, bound_rules, profile):
    """An engine with no decks to show, so every round is a direct question."""
    return Engine(catalog=catalog, rules=bound_rules, profile=profile, decks={}, scores={})


def legal_pool(catalog, bound_rules) -> set[str]:
    """Every card that could contribute to a legal deck for this legend."""
    legend = catalog.get(LEGEND)
    pool = {c.card_id for c in legal_main_pool(legend, catalog=catalog, rules=bound_rules)}
    for card_type in ("Rune", "Battlefield"):
        pool |= {
            c.card_id
            for c in legal_zone_pool(legend, card_type, catalog=catalog, rules=bound_rules)
        }
    return pool


def test_we_never_say_no_while_holding_a_card_we_never_asked_about(
    bare_engine, catalog, bound_rules
):
    """The false negative, as an invariant.

    A collection-wide sweep found one: a player who could build was told they could not,
    because each round estimated how many names would be enough, the estimate stayed
    optimistic, and the session ran out of rounds still holding a pool it had never
    asked about. "You cannot build this" is only honest once nothing is left to ask.
    """
    session = bare_engine.start(LEGEND)
    asked: set[str] = set()
    for _ in range(8):
        proposal = bare_engine.propose(session)
        if proposal.phase == PHASE_DONE:
            break
        assert proposal.question is not None
        asked |= set(proposal.question.card_ids)
        # Owns none of them — the hardest possible answer.
        session = bare_engine.answer_question(session, {}, proposal.question.card_ids)
    else:
        pytest.fail("the session never concluded")

    assert proposal.floor is None, "this player owns nothing; there is nothing to build"
    unasked = legal_pool(catalog, bound_rules) - asked
    assert not unasked, f"said no while never asking about {sorted(unasked)}"


def test_the_questions_run_out_instead_of_repeating(bare_engine, catalog, bound_rules):
    """A question never re-asks, so the session always terminates.

    The failure mode being ruled out is a loop: estimate, come back short, estimate the
    same size again. Each round strictly shrinks what is left to ask, so the sequence
    ends — and by then it has covered the pool.
    """
    session = bare_engine.start(LEGEND)
    seen: set[str] = set()
    rounds = 0
    while (question := bare_engine.propose(session).question) is not None:
        rounds += 1
        assert not set(question.card_ids) & seen, "asked the same card twice"
        seen |= set(question.card_ids)
        session = bare_engine.answer_question(session, {}, question.card_ids)
        assert rounds <= 4, "should have run out of things to ask by now"
    assert seen >= legal_pool(catalog, bound_rules)


def test_the_question_is_sized_to_the_player_not_to_the_average(bare_engine, catalog):
    """Rarity priors describe an average collection; the people who need this question
    are the ones furthest from average, so the estimate has to learn from their answers.
    """
    fillers = [f"filler-{i:02d}" for i in range(1, 15)]
    poor = bare_engine.start(LEGEND, prior=Knowledge(exact={c: 0 for c in fillers}))
    rich = bare_engine.start(LEGEND, prior=Knowledge(exact={c: 3 for c in fillers}))

    poor_q = bare_engine.propose(poor).question
    rich_q = bare_engine.propose(rich).question
    assert poor_q is not None and rich_q is not None
    assert len(poor_q.card_ids) >= len(rich_q.card_ids)
