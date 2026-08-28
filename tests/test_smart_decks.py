"""The Smart Decks session engine.

The subtle parts are the knowledge semantics — what an answer actually tells us — and
they are where the real bug lived. See
:func:`test_saying_you_have_all_of_them_does_not_cap_your_collection`.
"""

from __future__ import annotations

import inspect
import random
from dataclasses import replace

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
    declared_knowledge,
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


def short_on_main(deck: Deck) -> dict[str, int]:
    """Own everything the deck needs except its main-deck cards.

    The shared catalogue has exactly one legal champion, one legal rune and three
    battlefields, all three of which this deck plays. Answering 0 to any of those leaves
    a requirement whose whole pool is known and still short -- which the engine now
    correctly reports as impossible rather than asking on. Only the main pool has spare
    cards (filler-10..14), so main is the one requirement that can be short *and* still
    worth a question here.
    """
    have = dict(deck_requirements(deck))
    for card_id in deck.main:
        if card_id != deck.champion_id:
            have[card_id] = 0
    return have


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
    """A question aimed at the binding requirement beats another near-identical deck.

    They keep the legend and champion, because without those the honest answer is not a
    question at all -- this catalogue has a single legal champion, so a player who has
    told us they own none of it cannot build with this legend whatever else they say,
    and the session now ends instead of asking. That case is covered by
    :func:`test_a_legend_you_do_not_own_ends_the_session_instead_of_sweeping`.
    """
    session = engine.start(LEGEND)
    first = engine.propose(session)
    # Short of the main deck, but the pool still holds cards nobody has asked about.
    session = engine.answer(session, "d1", short_on_main(first.deck.deck))
    second = engine.propose(session)
    assert second.phase == PHASE_CHECKLIST
    assert second.question is not None and second.question.card_ids


def test_a_direct_question_covers_every_blocking_requirement_at_once(rules):
    """Asking them one at a time cost a round each.

    Built on its own catalogue rather than the shared one, which has a single legal
    champion and a single legal rune -- there, saying you own none of either settles the
    deck outright and the right answer is to stop, not to ask. Several walls that are
    each *still open* need pools with cards to spare, which is what this sets up.
    """
    from conftest import make_card

    legend_id = "spare-legend"
    cards = [
        make_card(legend_id, "Spare Legend", card_type="Legend", domains=("Fury",),
                  cost=None, might=None, tags=("Spare",), champion_tags=("Spare",)),
        *[
            make_card(f"champ-{i}", f"Champ {i}", super_type="Champion",
                      domains=("Fury",), tags=("Spare",), champion_tags=("Spare",))
            for i in (1, 2)
        ],
        *[
            make_card(f"rune-{i}", f"Rune {i}", card_type="Rune", super_type="Basic",
                      domains=("Fury",), cost=None, might=None)
            for i in (1, 2)
        ],
        *[
            make_card(f"field-{i}", f"Field {i}", card_type="Battlefield",
                      domains=("Fury",), cost=None, might=None)
            for i in range(1, 6)
        ],
        *[make_card(f"body-{i:02d}", f"Body {i:02d}", domains=("Fury",))
          for i in range(1, 20)],
    ]
    from riftbound.domain.cards import build_catalog

    catalog = build_catalog(cards)
    bound = rules.bind(catalog)
    main = {"champ-1": 3}
    main.update({f"body-{i:02d}": 3 for i in range(1, 13)})
    deck = Deck.make(legend_id=legend_id, champion_id="champ-1", main=main,
                     runes={"rune-1": 12}, battlefields=["field-1", "field-2", "field-3"])
    decks = {"d1": as_meta(deck, "d1")}
    profile = build_index(decks.values(), {"d1": 1.0}).get(legend_id)
    engine = Engine(catalog=catalog, rules=bound, profile=profile,
                    decks=decks, scores={"d1": 1.0})

    session = engine.start(legend_id)
    first = engine.propose(session)
    partial = {c: 0 for c in deck_requirements(first.deck.deck)}
    partial[legend_id] = 1
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
    """And says *what* is missing, not just that something is.

    This used to report the generic shortfall -- "Short by 1 more legend, ..." -- after
    working through the whole pool to get there. Owning none of the legend card settles
    it immediately, so the session says which card and why nothing substitutes.
    """
    run = run_to_completion(engine, LEGEND, {})
    assert run.floor is None
    assert run.proposal.phase == PHASE_DONE
    assert "Vi - Piltover Enforcer" in run.proposal.reason
    assert "stand in for it" in run.proposal.reason


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


# -- banned cards -------------------------------------------------------------


def test_a_banned_card_is_never_put_in_front_of_the_player(catalog, bound_rules, profile):
    """A banned deck keeps its signal; it just stops being a suggestion.

    The deck was played and its other cards say something true about the format, so it
    stays in the meta data and keeps counting toward trends. What it must not do is ask
    somebody "do you own Obelisk of Power?" -- inviting them to go and find a card they
    are not allowed to play.
    """
    tainted = a_deck(main={**a_deck().main, "banned-blade": 2})
    engine = Engine(
        catalog=catalog, rules=bound_rules, profile=profile,
        decks={"d1": as_meta(tainted, "d1")}, scores={"d1": 1.0},
    )
    proposal = engine.propose(engine.start(LEGEND))
    assert proposal.deck is not None
    assert "banned-blade" not in proposal.deck.deck.main
    assert "banned-blade" not in deck_requirements(proposal.deck.deck)


def test_stripping_a_banned_card_leaves_the_rest_of_the_deck_alone(catalog, bound_rules, profile):
    """Only the illegal card goes; the deck is otherwise the deck that was played."""
    original = a_deck()
    tainted = a_deck(main={**original.main, "banned-blade": 2})
    engine = Engine(
        catalog=catalog, rules=bound_rules, profile=profile,
        decks={"d1": as_meta(tainted, "d1")}, scores={"d1": 1.0},
    )
    shown = engine.propose(engine.start(LEGEND)).deck
    assert shown is not None
    assert dict(shown.deck.main) == dict(original.main)
    assert shown.deck.runes == original.runes
    assert shown.deck.battlefields == original.battlefields


def test_a_clean_deck_is_passed_through_untouched(catalog, bound_rules, profile):
    """No copying, no rebuilding, for the overwhelming majority that need nothing."""
    engine = Engine(
        catalog=catalog, rules=bound_rules, profile=profile,
        decks={"d1": as_meta(a_deck(), "d1")}, scores={"d1": 1.0},
    )
    shown = engine.propose(engine.start(LEGEND)).deck
    assert shown is engine.decks["d1"]


# -- "I don't want to play this" ------------------------------------------------
#
# A different claim from "I haven't got this", and the wizard has to keep them apart.
# Folding a preference in as `exact 0` would make it tell someone they cannot build a
# deck they own every card for, and would write "does not own" into their collection on
# the opt-in save. The point of the feature: a tool that can only hear the second can
# only ever build the meta back at you.


def test_a_declined_card_is_not_built_with():
    knowledge = Knowledge(exact={"a": 3, "b": 3})
    assert knowledge.owned() == {"a": 3, "b": 3}
    assert knowledge.declining(["a"]).owned() == {"b": 3}


def test_declining_does_not_claim_the_player_lacks_the_card():
    """The distinction the separate state exists for."""
    knowledge = Knowledge(exact={"a": 3}).declining(["a"])
    assert knowledge.is_declined("a")
    # The ownership record is untouched: they still told us they have three.
    assert knowledge.exact["a"] == 3


def test_a_decline_can_be_taken_back():
    knowledge = Knowledge(exact={"a": 3}).declining(["a"])
    assert knowledge.allowing(["a"]).owned() == {"a": 3}
    assert not knowledge.allowing(["a"]).is_declined("a")


def test_declines_accumulate_across_passes():
    knowledge = Knowledge(exact={"a": 3, "b": 3, "c": 3})
    twice = knowledge.declining(["a"]).declining(["b"])
    assert twice.declined == frozenset({"a", "b"})
    assert twice.owned() == {"c": 3}


def test_answering_a_round_keeps_what_was_declined():
    """A later answer must not quietly reinstate a card the player ruled out."""
    knowledge = Knowledge(exact={"a": 3}).declining(["a"])
    after = knowledge.with_answer({"a": 3, "b": 3}, {"a": 3, "b": 3})
    assert after.is_declined("a")
    assert "a" not in after.owned()


def test_declining_nothing_changes_nothing():
    knowledge = Knowledge(exact={"a": 3})
    assert knowledge.declining([]) is knowledge
    assert knowledge.allowing(["never-declined"]) is knowledge


# -- what a session costs the player ------------------------------------------
#
# Rounds are screens; cards are decisions. Every acceptance metric counted screens,
# which is how a 241-card sweep passed as "two rounds" and why the cost of being told
# "no" -- the larger population -- was outside all of them.


def test_a_run_counts_the_cards_it_put_in_front_of_the_player(engine, catalog):
    """The tally comes from the driving loop, not from a copy of it.

    A harness that reimplemented this loop to count separately would drift from the
    engine the moment either changed, and the number would quietly stop describing the
    thing it names.
    """
    run = run_to_completion(engine, LEGEND, full_owned(catalog))
    assert run.cards_per_round, "a session that asked something must record it"
    assert len(run.cards_per_round) == run.rounds
    assert run.cards_asked == sum(run.cards_per_round)
    assert run.largest_round == max(run.cards_per_round)


def test_the_cost_of_a_no_is_not_averaged_into_the_cost_of_a_yes(engine):
    """``cards_to_answer`` is None when no deck ever appeared.

    Folding a session that ended in nothing into the same median as one that produced a
    deck would flatter both: the failures are the long ones, and they have nothing to
    show for the length.
    """
    run = run_to_completion(engine, LEGEND, {})
    assert run.floor is None
    assert run.cards_to_answer is None
    assert run.cards_asked > 0, "it still asked, it just never answered"


def test_cards_to_answer_counts_only_the_rounds_before_the_deck(engine, catalog):
    run = run_to_completion(engine, LEGEND, full_owned(catalog))
    assert run.rounds_to_answer is not None
    assert run.cards_to_answer == sum(run.cards_per_round[: run.rounds_to_answer])
    assert run.cards_to_answer <= run.cards_asked


def test_the_report_measures_the_players_who_are_told_no(catalog, bound_rules):
    """``infeasible`` is the population every other metric skips.

    ``solved_when_feasible``, ``false_negatives`` and ``rounds_to_answer`` are all
    computed over feasible players only. On the live snapshot that leaves 697 of 980
    sessions -- the ones that end with nothing -- outside every gate.
    """
    decks = {"d1": as_meta(a_deck(), "d1")}
    index = build_index(decks.values(), {"d1": 1.0})
    rng = random.Random(4)
    players = [
        Player(name=f"p{i}", owned=random_collection(catalog, rng=rng, scale=0.3))
        for i in range(4)
    ]
    report = simulate(
        catalog=catalog, rules=bound_rules, index=index, decks=decks.values(),
        scores={"d1": 1.0}, legends=[LEGEND], players=players,
    )
    assert len(report.feasible) + len(report.infeasible) == len(report.outcomes)
    assert report.infeasible, "thin collections must produce the population under test"
    for outcome in report.infeasible:
        assert not outcome.feasible
    assert report.cards_to_no, "a player told no still answered questions to get there"
    assert report.median_cards_to_no > 0


def test_the_card_targets_gate_the_release():
    """Folded into ``passes`` now that the closing question can meet them.

    The guard that used to live here asserted the opposite, and said to delete itself
    once this was true. It did its job.
    """
    from riftbound.domain.smart_decks_harness import Report

    assert "card_targets_met" in inspect.getsource(Report.passes.fget)


# -- when the answer is settled -----------------------------------------------


def test_a_legend_you_do_not_own_ends_the_session_instead_of_sweeping(engine):
    """The 241-card screen, and why it existed.

    The sweep is there so we never say "you cannot build this" while holding names we
    have not asked about. But a legend deck needs its own legend card, and nothing
    substitutes -- so once the player has said they own none, every further question is
    about cards that cannot change the answer. On the live snapshot this was 85% of the
    sessions that ended in "no", each one asking ~270 more cards after the point it was
    already settled.
    """
    session = engine.start(LEGEND)
    first = engine.propose(session)
    have = {c: 3 for c in deck_requirements(first.deck.deck)}
    have[LEGEND] = 0
    session = engine.answer(session, "d1", have)

    proposal = engine.propose(session)
    assert proposal.phase == PHASE_DONE
    assert proposal.question is None, "nothing left worth asking"
    assert "Vi - Piltover Enforcer" in proposal.reason


def test_it_still_sweeps_while_an_unasked_card_could_change_the_answer(engine):
    """The rule the sweep protects, kept intact.

    Being short of main-deck cards is not settled: the pool holds cards nobody has been
    asked about, any of which could close the gap. So the session keeps asking, and only
    the *provably* unanswerable case short-circuits.
    """
    session = engine.start(LEGEND)
    first = engine.propose(session)
    session = engine.answer(session, "d1", short_on_main(first.deck.deck))

    proposal = engine.propose(session)
    assert proposal.phase == PHASE_CHECKLIST
    assert proposal.question is not None and proposal.question.card_ids


def test_no_single_screen_exceeds_the_checklist_cap(catalog, bound_rules, profile):
    """``MAX_CHECKLIST`` is a cap the engine claimed and the sweep path ignored.

    The sweep returned the whole remaining pool in one go. It is paged now: answered
    cards become known exactly, ``ranked`` drops them, and the next round continues
    where the last stopped, so nothing is skipped and no certainty is traded away.
    """
    from riftbound.domain.smart_decks.engine import MAX_CHECKLIST

    decks = {"d1": as_meta(a_deck(), "d1")}
    engine = Engine(catalog=catalog, rules=bound_rules, profile=profile,
                    decks=decks, scores={"d1": 1.0})
    rng = random.Random(7)
    for scale in (0.2, 0.4, 0.6):
        owned = random_collection(catalog, rng=rng, scale=scale)
        owned[LEGEND] = 1          # keep it askable rather than settled
        run = run_to_completion(engine, LEGEND, owned)
        assert run.largest_round <= MAX_CHECKLIST, run.cards_per_round


# -- what the player told us before the wizard asked --------------------------


def a_profile(**kw):
    from riftbound.domain.availability import AvailabilityProfile
    return AvailabilityProfile(**kw)


def test_an_exclusion_rule_is_a_statement_of_absence(catalog):
    """"No Epics" is one click, and the wizard used to ignore it entirely.

    Every Epic in the opening checklist was shown pre-filled as *owned*, so the player
    had to say a second time, card by card, what a rule had already said.
    """
    from riftbound.domain.availability import MODE_EXCLUSION, ExclusionRule

    knowledge = declared_knowledge(
        a_profile(mode=MODE_EXCLUSION, exclusion_rules=(ExclusionRule("rarity", "Epic"),)),
        catalog,
    )
    assert knowledge.is_exact("harpoon-squad")        # the Epic in this catalogue
    assert knowledge.lower_bound("harpoon-squad") == 0
    assert not knowledge.is_known("brazen-buccaneer"), "a rule says nothing about commons"


def test_a_partial_collection_seeds_what_it_holds_and_stays_quiet_otherwise(catalog):
    """Silence in a collection is not a claim of absence.

    Most people record the decks they play, not their binder. Reading "not written
    down" as "does not own" is the assumption behind v2's
    ``strictBuildableEmptyResultRate: 0.814`` -- asked for a deck from a collection it
    returned nothing four times in five.
    """
    from riftbound.domain.availability import MODE_COLLECTION

    knowledge = declared_knowledge(
        a_profile(mode=MODE_COLLECTION, owned={"brazen-buccaneer": 2}), catalog
    )
    assert knowledge.lower_bound("brazen-buccaneer") == 2
    assert not knowledge.is_known("harpoon-squad"), "unrecorded is unknown, not absent"


def test_strict_collection_mode_does_read_silence_as_absence(catalog):
    """Because the player asked for it by name: "only what I can build now"."""
    from riftbound.domain.availability import MODE_COLLECTION

    knowledge = declared_knowledge(
        a_profile(mode=MODE_COLLECTION, owned={"brazen-buccaneer": 2}, strict=True),
        catalog,
    )
    assert knowledge.is_exact("harpoon-squad")
    assert knowledge.lower_bound("harpoon-squad") == 0


def test_a_declaration_does_not_pose_as_a_sample_of_the_collection(catalog):
    """The regression that made honouring declarations *worse* than ignoring them.

    Calibration asks how optimistic the rarity priors have proved for this player, by
    comparing copies reported against copies expected across everything asked. A
    declaration is chosen precisely because it is absent, so folding it into that
    comparison reads as evidence they own little of everything. Seeding 151
    declared-absent cards floored the estimate and pushed the median session from 47
    cards to 85 -- the fix is that declared ids are exact but not counted as answers.
    """
    from riftbound.domain.availability import MODE_EXCLUSION, ExclusionRule

    knowledge = declared_knowledge(
        a_profile(mode=MODE_EXCLUSION, exclusion_rules=(ExclusionRule("rarity", "Epic"),)),
        catalog,
    )
    assert knowledge.assumed, "declared ids must be marked"
    assert set(knowledge.assumed) <= set(knowledge.exact)
    assert all(knowledge.is_exact(c) for c in knowledge.assumed), "still exact"


def test_answering_turns_an_assumption_into_evidence(catalog):
    """A rule is broad; an answer is about one card, and it wins.

    Ticking "no Epics" and then saying "actually I have one of those" has to leave the
    exception standing -- and once answered, the card is real evidence again.
    """
    from riftbound.domain.availability import MODE_EXCLUSION, ExclusionRule

    knowledge = declared_knowledge(
        a_profile(mode=MODE_EXCLUSION, exclusion_rules=(ExclusionRule("rarity", "Epic"),)),
        catalog,
    )
    assert "harpoon-squad" in knowledge.assumed
    answered = knowledge.with_answer({"harpoon-squad": 3}, {"harpoon-squad": 2})
    assert answered.lower_bound("harpoon-squad") == 2
    assert "harpoon-squad" not in answered.assumed


def test_a_checklist_answer_does_not_wipe_what_they_declined(engine):
    """Found while wiring declarations through.

    ``answer_question`` rebuilt Knowledge without ``declined``, so a card the player had
    said they did not want to play came back in the next deck as soon as they answered
    any checklist.
    """
    session = engine.start(LEGEND)
    session = replace(session, knowledge=session.knowledge.declining(["harpoon-squad"]))
    assert session.knowledge.is_declined("harpoon-squad")

    session = engine.answer_question(session, {"brazen-buccaneer": 1}, ["brazen-buccaneer"])
    assert session.knowledge.is_declined("harpoon-squad"), "a decline must survive a round"


# -- keeping the shape of a repaired deck --------------------------------------
#
# Measured over 500 repairs of real lists against synthetic collections: the field
# plays 18 unique main-deck cards (median, stdev 1.9) at 25% one-ofs / 29% two-ofs /
# 46% three-ofs. Repairing a hole at a time returned 24 unique cards at 48/39/14, with
# 89% of results wider than any list the field actually plays.


def test_one_playset_covers_several_holes_rather_than_several_names(engine, catalog,
                                                                    bound_rules, profile):
    """The change that mattered, and it is arithmetic rather than judgement.

    67.6% of holes are a single copy, and the hole itself is the binding limit on 86.5%
    of fills -- so filling holes independently took one copy of one new card each time,
    and a list short six copies came back six names wider. Holes are pooled per zone, so
    a candidate can arrive as the playset the field runs it as and cover the next holes
    with it.
    """
    deck = a_deck()
    # A field that runs filler-10 as a playset, so the profile knows its count. Without
    # that the repair is right to bring an unknown card in as a single copy -- it has no
    # evidence anybody plays it as more.
    staple = dict(deck.main)
    staple["filler-10"] = 3
    for card_id in ("filler-01", "filler-02", "filler-03"):
        staple.pop(card_id, None)
    field = {
        "d1": as_meta(deck, "d1"),
        "d2": as_meta(a_deck(main=staple), "d2"),
        "d3": as_meta(a_deck(main=staple), "d3"),
    }
    rich = build_index(field.values(), {k: 1.0 for k in field}).get(LEGEND)
    assert rich.copies.get("filler-10") == 3, "the field plays it as a playset"

    # Short one copy each of three different cards: three separate one-copy holes.
    short = ["filler-01", "filler-02", "filler-03"]
    owned = full_owned(catalog)
    for card_id in short:
        owned[card_id] = 2
    fixed = repair(deck, known(owned), profile=rich, catalog=catalog,
                   rules=bound_rules, conservative=False)
    assert fixed is not None
    brought_in = {s.in_card_id for s in fixed.swaps}
    assert len(brought_in) < len(short), (
        "three one-copy holes must not become three new names"
    )


def test_a_repair_does_not_widen_a_deck_without_limit(engine, catalog, bound_rules, profile):
    """A repaired list stays within the range the field actually plays.

    The published range is 10-30 unique main-deck cards. A repair that answers by adding
    a new name per missing copy leaves the player holding something no one has played.
    """
    deck = a_deck()
    owned = full_owned(catalog)
    for card_id in [f"filler-{i:02d}" for i in range(1, 6)]:
        owned[card_id] = 1
    fixed = repair(deck, known(owned), profile=profile, catalog=catalog,
                   rules=bound_rules, conservative=False)
    if fixed is None:
        pytest.skip("this collection could not be repaired at all")
    assert len(fixed.deck.main) <= len(deck.main) + 5


def test_shape_never_costs_an_answer(catalog, bound_rules, profile):
    """The second pass exists for this.

    Preferring the field's own counts is a preference, not a constraint: somebody short
    of cards would rather hold a deck with an odd curve than be told no, so the fill
    drops the shape rule before it drops the answer.
    """
    deck = a_deck()
    rng = random.Random(19)
    answered = 0
    for _ in range(12):
        owned = random_collection(catalog, rng=rng, scale=0.9)
        owned[LEGEND] = 1
        owned["vi-destructive"] = 3
        for card_id, n in deck.runes.items():
            owned[card_id] = n
        for card_id in deck.battlefields:
            owned[card_id] = 1
        if repair(deck, known(owned), profile=profile, catalog=catalog,
                  rules=bound_rules, conservative=False) is not None:
            answered += 1
    assert answered, "the shape preference must not make every repair fail"


# -- dropping a card the player owns -------------------------------------------


def test_a_stub_is_only_the_case_the_field_will_not_play(catalog, bound_rules, profile):
    """Measured across every card played in 20 or more lists:

      the field runs 3, deck left at 2 -- played 18.2% of the time
      the field runs 2, deck left at 1 -- played 19.9% of the time
      the field runs 3, deck left at 1 -- played  4.7% (median 1.9%)

    Only the last is a quantity nobody plays, so only the last is a stub. The other two
    are real decks and cutting them would be throwing away a card for nothing.
    """
    from riftbound.domain.smart_decks.repair import _is_stub

    deck = a_deck()
    playset = next(c for c in deck.main if profile.copies.get(c) == 3
                   and c != deck.champion_id)

    class _Hole:
        def __init__(self, card_id, have):
            self.card_id, self.have = card_id, have

    assert _is_stub(profile, _Hole(playset, 1), "main", deck)
    assert not _is_stub(profile, _Hole(playset, 2), "main", deck), "a two-of is a real deck"
    assert not _is_stub(profile, _Hole(deck.champion_id, 1), "main", deck), (
        "the champion defines the deck"
    )
    assert not _is_stub(profile, _Hole(playset, 1), "runes", deck), (
        "runes are a resource base, not a curve"
    )


def test_cutting_is_considered_but_only_taken_when_it_wins(catalog, bound_rules, profile):
    """"Sometimes the right move" has to mean sometimes.

    Cutting every stub is plainly wrong: measured over 400 repairs where the choice
    mattered, it lost play-rate mass 97% of the time -- a median 5.25% -- to save one
    card of width. So the cut is built and compared like any other candidate repair, and
    kept only when the deck it produces is actually better. Ties keep the card the
    player owns.
    """
    from riftbound.domain.smart_decks.repair import _attempt, _mass

    deck = a_deck()
    owned = full_owned(catalog)
    playset = next(c for c in deck.main if profile.copies.get(c) == 3
                   and c != deck.champion_id)
    owned[playset] = 1                      # exactly the stub case
    holes = gaps_for(deck, known(owned))
    legend = catalog.get(LEGEND)

    kw = dict(profile=profile, catalog=catalog, rules=bound_rules, legend=legend,
              owned=known(owned).owned(), allowed=None, conservative=False)
    patched = _attempt(deck, holes, cut_stubs=False, **kw)
    cut = _attempt(deck, holes, cut_stubs=True, **kw)
    shipped = repair(deck, known(owned), profile=profile, catalog=catalog,
                     rules=bound_rules, conservative=False)
    assert shipped is not None

    if patched is not None and cut is not None:
        assert _mass(shipped.deck, profile) >= min(
            _mass(patched.deck, profile), _mass(cut.deck, profile)
        )
        # Never worse than simply keeping the stub.
        assert _mass(shipped.deck, profile) >= _mass(patched.deck, profile)
