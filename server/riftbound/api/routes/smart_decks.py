"""Smart Decks: the deck-building wizard.

Sessions are stored server-side and every round is written as it is answered. The
answers are the expensive part -- three deck rounds pin down roughly 75 cards -- so a
closed tab must not cost them.

The engine itself is pure (``domain/smart_decks.py``); everything here is translation:
record -> domain session, proposal -> view, and the two write actions at the end.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from ...domain.availability import deck_coverage
from ...domain.bans import notices_for
from ...domain.deck import Deck
from ...domain.meta_scoring import score_deck
from ...domain.smart_decks import (
    Engine,
    Knowledge,
    Proposal,
    Session,
    deck_requirements,
    declared_knowledge,
    gaps_for,
)
from ...domain.validator import validate
from ...infra.repos import WizardSessionRecord
from ...services import Services, get_services
from ..identity import Identity, current_identity
from ..schemas import (
    AcceptRequest,
    AnswerRequest,
    BanNoticeView,
    DeckScoreView,
    DeclinedCardView,
    DeclineRequest,
    FloorView,
    GapView,
    LegendChoiceView,
    ProposalView,
    QuestionView,
    SaveCollectionRequest,
    SaveCollectionResult,
    SmartSessionView,
    StartSessionRequest,
)
from ..views import (
    deck_card_rows,
    deck_dict,
    deck_score_view,
    meta_deck_view,
    repair_view,
    requirement_row,
)

router = APIRouter(prefix="/api/smart-decks", tags=["smart-decks"])

#: How many of a legend's most-played cards to weigh when estimating familiarity.
FAMILIARITY_DEPTH = 20

#: Orderings the picker offers. A sort, never a filter -- see :func:`list_legends`.
SORT_STRENGTH = "strength"
SORT_BUILDABLE = "buildable"
#: Order by how the legend fares against the field as it is actually played, rather
#: than by the pedigree of its best published list. The two disagree exactly where a
#: player most needs them to: a legend whose strongest list won a major can still be
#: badly placed if the decks it loses to are the ones everybody brings.
SORT_FIELD = "field"
SORTS = (SORT_STRENGTH, SORT_BUILDABLE, SORT_FIELD)

#: A card played in at least this share of a legend's decks is a staple.
STAPLE_SHARE = 0.5


def _engine(services: Services, legend_id: str) -> Engine:
    engine = services.engine_for(legend_id)
    if engine is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No meta decks for legend {legend_id!r}. The wizard builds from what "
                "the field is playing, so a legend with no published decks has nothing "
                "to propose yet."
            ),
        )
    return engine


def _declared(services: Services, user_id: str) -> Knowledge:
    """What the player told us outside the wizard, as prior knowledge."""
    profile = services.availability.load(user_id=user_id)
    return declared_knowledge(profile, services.catalog)


def _session_of(
    record: WizardSessionRecord, prior: Knowledge | None = None
) -> Session:
    """Rebuild a stored session, with anything declared elsewhere underneath it.

    The prior goes *under* the recorded answers, never over them. A declaration is a
    broad statement -- "no Epics" covers cards the player has never thought about -- so
    the one place it must yield is where they have since answered for a specific card.
    Ticking a rule and then saying "actually I have one of those" leaves the exception
    standing.
    """
    prior_exact = dict(prior.exact) if prior else {}
    prior_at_least = dict(prior.at_least) if prior else {}

    # An answer about one card overrides a declaration about its whole class, and it has
    # to override *both* halves. ``lower_bound`` takes the max of exact and at_least, so
    # leaving a declared "all Commons" in place next to an answered "I have none of this
    # Common" would let the broad claim win the very comparison it should lose.
    for card_id in (*record.exact, *record.at_least):
        prior_exact.pop(card_id, None)
        prior_at_least.pop(card_id, None)

    return Session(
        legend_id=record.legend_id,
        knowledge=Knowledge(
            exact={**prior_exact, **record.exact},
            at_least={**prior_at_least, **record.at_least},
            declined=frozenset(record.declined),
            assumed=frozenset(prior_exact),
        ),
        asked=record.asked_deck_ids,
        phase=record.phase,
        checklists=record.checklists,
    )


def _load(services: Services, session_id: str, user_id: str) -> WizardSessionRecord:
    record = services.smart_decks.get(session_id, user_id=user_id)
    if record is None:
        raise HTTPException(status_code=404, detail="No such wizard session.")
    return record


def _checklist_ceiling(card_id: str, catalog) -> int:
    """How many copies a checklist row should offer.

    A checklist asks "how many do you own", not "have you enough for this deck", so the
    ceiling is the copy limit rather than any one deck's requirement. Runes are the
    exception the format makes: decks run twelve.
    """
    card = catalog.get(card_id)
    if card is None:
        return 3
    if card.card_type == "Rune":
        return 12
    if card.card_type in ("Legend", "Battlefield") or card.unique:
        return 1
    return 3


def _score_view(score) -> DeckScoreView | None:
    if score is None:
        return None
    return deck_score_view(score)


def _floor_view(
    deck: Deck | None, engine: Engine, score=None, catalog=None
) -> FloorView | None:
    if deck is None:
        return None
    play_rate = engine.profile.play_rate
    staples = sum(1 for c in deck.main if play_rate.get(c, 0.0) >= STAPLE_SHARE)
    return FloorView(
        deck=deck_dict(deck),
        quality=sum(play_rate.get(c, 0.0) * n for c, n in deck.main.items()),
        summary=(
            f"{sum(deck.main.values())} cards you can field today, "
            f"{staples} of them staples the field plays for this legend."
        ),
        score=_score_view(score),
        cards=deck_card_rows(deck, catalog) if catalog is not None else [],
    )


def _feasibility_line(proposal: Proposal, session: Session) -> str:
    """What we can say about whether they can build this, without overstating it.

    Feasibility is computed from what the player has told us, so before they have told
    us anything it reads "Short by 1 more legend, 1 more champion, 40 more main" -- a
    verdict on a collection nobody has asked about, delivered on the opening screen. It
    is technically what the function measured and it is not what a person reads: it says
    "you cannot build this", when the truth is "we have not asked yet".
    """
    if proposal.feasibility is None:
        return ""
    # Whether *they* have told us anything, not whether the session holds knowledge.
    # It always holds some: runes are assumed, and a declared collection is seeded before
    # the first question. Neither is an answer to a question we have asked.
    if not session.asked and not session.checklists:
        return "Mark anything you are short of and we will work out what you can build."
    return proposal.feasibility.describe()


def _proposal_view(
    proposal: Proposal, session: Session, engine: Engine, services: Services, user_id: str
) -> ProposalView:
    catalog = services.catalog
    knowledge = session.knowledge
    view = ProposalView(
        phase=proposal.phase,
        reason=proposal.reason,
        round=session.rounds + session.checklists,
        floor=_floor_view(proposal.floor, engine, proposal.floor_score, catalog),
        chosen=proposal.chosen,
        deck_score=_score_view(proposal.deck_score),
        feasibility=_feasibility_line(proposal, session),
        can_build=bool(proposal.feasibility and proposal.feasibility.ok),
    )

    if proposal.deck is not None:
        meta = proposal.deck
        required = deck_requirements(meta.deck)
        availability = services.availability.load(user_id=user_id)
        view.deck = meta_deck_view(
            meta,
            score_deck(meta),
            deck_coverage(required, profile=availability, catalog=catalog),
            catalog,
        )
        view.requirements = [
            requirement_row(card_id, needed, meta.deck.zone_of(card_id), knowledge, catalog)
            for card_id, needed in required.items()
        ]
        view.gaps = [
            GapView(
                card_id=gap.card_id,
                name=getattr(catalog.get(gap.card_id), "name", gap.card_id),
                needed=gap.needed,
                have=gap.have,
                short=gap.short,
            )
            for gap in gaps_for(meta.deck, knowledge)
        ]

    rules = services.rules_for("constructed")
    for field_name in ("conservative", "free"):
        fix = getattr(proposal, field_name)
        if fix is not None:
            legal = validate(fix.deck, rules=rules, catalog=catalog).legal
            built = repair_view(fix, catalog, legal=legal)
            built.score = _score_view(getattr(proposal, f"{field_name}_score"))
            setattr(view, field_name, built)

    # Ban warnings, for the deck we would hand over and for the published list we are
    # asking about. Both matter and they say different things: one is "this is in your
    # deck", the other "this is why our version differs from the original".
    considered = list(deck_requirements(proposal.deck.deck)) if proposal.deck else []
    notices = notices_for(
        proposal.floor, rules=rules, catalog=catalog, considered=considered
    )
    view.ban_notices = [
        BanNoticeView(
            card_id=notice.card_id,
            name=notice.name,
            source=notice.source,
            enforced=notice.enforced,
            in_deck=notice.in_deck,
            message=notice.describe(rules.format_name),
        )
        for notice in notices
    ]

    if proposal.question is not None:
        view.question = QuestionView(
            reason=proposal.question.reason,
            cards=[
                requirement_row(
                    card_id,
                    _checklist_ceiling(card_id, catalog),
                    "ask",
                    knowledge,
                    catalog,
                    assume_owned=False,
                )
                for card_id in proposal.question.card_ids
            ],
        )
    return view


def _session_view(
    record: WizardSessionRecord,
    services: Services,
    user_id: str,
    *,
    with_proposal: bool = True,
    computed: tuple[Session, Engine, Proposal] | None = None,
) -> SmartSessionView:
    """Build the response view.

    ``propose()`` runs the repair engine and scores every candidate deck -- it is the
    single most expensive call in the wizard, and every route that mutates a session
    (``answer``) needs its result twice: once to decide what phase to persist, once to
    render the response. ``computed`` lets a caller that already ran it hand the same
    (session, engine, proposal) back in, so this only runs it itself when nobody has.
    """
    legend = services.catalog.get(record.legend_id)
    proposal = None
    if computed is not None:
        session, engine, domain_proposal = computed
        proposal = _proposal_view(domain_proposal, session, engine, services, user_id)
    elif with_proposal:
        session = _session_of(record, _declared(services, user_id))
        engine = _engine(services, record.legend_id)
        proposal = _proposal_view(
            engine.propose(session), session, engine, services, user_id
        )
    return SmartSessionView(
        session_id=record.session_id,
        legend_id=record.legend_id,
        legend_name=legend.name if legend else record.legend_id,
        phase=record.phase,
        rounds=len(record.asked_deck_ids) + record.checklists,
        known_cards=len(record.exact) + len(record.at_least),
        saved_deck_id=record.saved_deck_id,
        created_at=record.created_at,
        updated_at=record.updated_at,
        proposal=proposal,
        declined=[
            DeclinedCardView(
                card_id=card_id,
                name=getattr(services.catalog.get(card_id), "name", card_id),
                image_url=getattr(services.catalog.get(card_id), "image_url", ""),
            )
            for card_id in record.declined
        ],
    )


# -- legends ------------------------------------------------------------------


@router.get("/legends", response_model=list[LegendChoiceView])
def list_legends(
    sort: str = SORT_STRENGTH,
    services: Services = Depends(get_services),
    identity: Identity = Depends(current_identity),
) -> list[LegendChoiceView]:
    """Legends the wizard can build for, strongest first.

    ``familiarity`` never filters, and now optionally *orders*. The distinction is the
    whole of it: hiding a legend somebody could build with a little effort rebuilds the
    barrier the two-mode design removes, whereas letting them ask "which of these is
    closest to what I have" answers the question a player short of cards actually has.
    Every legend is always in the list; ``sort`` only changes what they read first.

    Default order is strength, because that is the right answer for somebody who has
    told us nothing -- which, on a first visit, is everybody.
    """
    catalog = services.catalog
    scores = services.deck_scores
    outlooks = services.field_outlooks

    # What we can assume they hold, from every source at once. Reading only the
    # collection table missed the whole of a declared collection: somebody who ticked
    # "all Commons" owns hundreds of cards and scored 0% familiar with every legend in
    # the game.
    owned = dict(services.collections.owned_by_card(user_id=identity.user_id))
    declared = declared_knowledge(
        services.availability.load(user_id=identity.user_id), catalog
    ).owned()
    for card_id, copies in declared.items():
        owned[card_id] = max(owned.get(card_id, 0), copies)

    # Which decks are tournament decks, by id. Counted per legend *below*, against the
    # profile's own decks rather than the whole archive -- the two were different
    # populations, and the subset was reported as larger than the whole: 27 of 49
    # legends read like "127 decks, 147 from tournaments". `deck_count` is scoped to the
    # current format era; this was not, so it also counted the pre-ban archive.
    tournament_decks = {
        deck.deck_id
        for deck in (services.meta.decks if services.meta is not None else ())
        if deck.provenance.evidence.startswith("tournament")
    }

    out: list[LegendChoiceView] = []
    for legend_id, profile in services.legend_index.profiles.items():
        card = catalog.get(legend_id)
        if card is None:
            continue
        # Runes are excluded: they are assumed available for everybody, so counting them
        # pads every legend's familiarity by the same amount and tells the player
        # nothing. "You own 60% of its staples" should mean the cards that vary.
        top = sorted(
            (c for c in profile.play_rate
             if getattr(catalog.get(c), "card_type", "") != "Rune"),
            key=lambda c: -profile.play_rate[c],
        )
        top = top[:FAMILIARITY_DEPTH]
        familiarity = (
            sum(1 for c in top if owned.get(c, 0) > 0) / len(top) if top and owned else 0.0
        )
        # The profile's clusters partition exactly the decks it was built from, so
        # counting within them cannot disagree with `deck_count` however the era is
        # scoped -- including the fallback profiles built from the whole archive.
        profile_decks = {d for c in profile.clusters for d in c.deck_ids}
        best = max((scores.get(d, 0.0) for d in profile_decks), default=0.0)
        outlook = outlooks.get(legend_id)
        out.append(
            LegendChoiceView(
                legend_id=legend_id,
                name=card.name,
                domains=list(card.domains),
                image_url=card.image_url,
                era_id=profile.era_id,
                deck_count=profile.deck_count,
                tournament_deck_count=len(profile_decks & tournament_decks),
                best_score=best,
                familiarity=familiarity,
                expected_win_rate=round(outlook.expected_win_rate, 4) if outlook else 0.0,
                field_delta=round(outlook.field_delta, 4) if outlook else 0.0,
                field_coverage=round(outlook.coverage, 4) if outlook else 0.0,
                field_shown=bool(outlook and outlook.shown),
            )
        )
    if sort == SORT_BUILDABLE:
        out.sort(key=lambda v: (-v.familiarity, -v.best_score, v.name))
    elif sort == SORT_FIELD:
        # Legends with no matchup evidence sort last rather than as 0% -- an unmeasured
        # legend is not a losing one, and burying it under everything rated would be a
        # filter wearing a sort's clothes.
        out.sort(key=lambda v: (not v.field_shown, -v.expected_win_rate, -v.best_score, v.name))
    else:
        out.sort(key=lambda v: (-v.best_score, -v.deck_count, v.name))
    return out


# -- sessions -----------------------------------------------------------------


@router.get("/sessions", response_model=list[SmartSessionView])
def list_sessions(
    limit: int = Query(20, ge=1, le=100),
    services: Services = Depends(get_services),
    identity: Identity = Depends(current_identity),
) -> list[SmartSessionView]:
    """Recent sessions, so an interrupted run can be picked back up."""
    return [
        _session_view(record, services, identity.user_id, with_proposal=False)
        for record in services.smart_decks.list(user_id=identity.user_id, limit=limit)
    ]


@router.post("/sessions", response_model=SmartSessionView, status_code=201)
def start_session(
    payload: StartSessionRequest,
    services: Services = Depends(get_services),
    identity: Identity = Depends(current_identity),
) -> SmartSessionView:
    _engine(services, payload.legend_id)  # 404 before writing anything
    session_id = services.smart_decks.create(
        user_id=identity.user_id, legend_id=payload.legend_id
    )
    return _session_view(_load(services, session_id, identity.user_id), services, identity.user_id)


@router.get("/sessions/{session_id}", response_model=SmartSessionView)
def get_session(
    session_id: str,
    services: Services = Depends(get_services),
    identity: Identity = Depends(current_identity),
) -> SmartSessionView:
    record = _load(services, session_id, identity.user_id)
    return _session_view(record, services, identity.user_id)


@router.post("/sessions/{session_id}/answer", response_model=SmartSessionView)
def answer(
    session_id: str,
    payload: AnswerRequest,
    services: Services = Depends(get_services),
    identity: Identity = Depends(current_identity),
) -> SmartSessionView:
    """Record one round and return the next proposal."""
    record = _load(services, session_id, identity.user_id)
    engine = _engine(services, record.legend_id)
    session = _session_of(record, _declared(services, identity.user_id))

    if payload.deck_id:
        if payload.deck_id not in engine.decks:
            raise HTTPException(
                status_code=400,
                detail=f"Deck {payload.deck_id!r} is not a deck for this legend.",
            )
        updated = engine.answer(session, payload.deck_id, payload.have)
        kind = "deck"
    else:
        if not payload.asked:
            raise HTTPException(
                status_code=400,
                detail=(
                    "A checklist answer must list the cards it covered. Without that, a "
                    "card left unticked is indistinguishable from one never shown, and "
                    "the difference is the whole point: one means none, the other means "
                    "we have not asked."
                ),
            )
        updated = engine.answer_question(session, payload.have, payload.asked)
        kind = "checklist"

    # Run once and reused below: `updated` is the exact session state being persisted,
    # so a second `propose()` against the reloaded record would recompute the same
    # repair and scoring work for the same answer.
    proposal = engine.propose(updated)

    services.smart_decks.record_round(
        session_id,
        user_id=identity.user_id,
        kind=kind,
        deck_id=payload.deck_id,
        answers=payload.have,
        exact=dict(updated.knowledge.exact),
        at_least=dict(updated.knowledge.at_least),
        phase=proposal.phase,
        checklists=updated.checklists,
    )
    return _session_view(
        _load(services, session_id, identity.user_id),
        services,
        identity.user_id,
        computed=(updated, engine, proposal),
    )


@router.post("/sessions/{session_id}/decline", response_model=SmartSessionView)
def decline(
    session_id: str,
    payload: DeclineRequest,
    services: Services = Depends(get_services),
    identity: Identity = Depends(current_identity),
) -> SmartSessionView:
    """Rule cards out by preference and rebuild around them.

    Not the same as saying you do not own something, and deliberately a separate
    endpoint. "I have none of these" is a fact about a collection, which the wizard
    stores as knowledge and can offer to write back; "I do not want to play this" is a
    fact about a person, which it stores separately and never writes anywhere. Filing
    the second as the first would make the app tell somebody they cannot build a deck
    they own every card for.

    The payload is the whole set rather than a delta, so taking a decline back is the
    same call as adding one.
    """
    record = _load(services, session_id, identity.user_id)
    if record.saved_deck_id:
        raise HTTPException(
            status_code=409,
            detail="This session already finished. Start another to build again.",
        )
    services.smart_decks.set_declined(
        session_id, user_id=identity.user_id, declined=payload.card_ids
    )
    return _session_view(
        _load(services, session_id, identity.user_id), services, identity.user_id
    )


@router.post("/sessions/{session_id}/accept", response_model=SmartSessionView)
def accept(
    session_id: str,
    payload: AcceptRequest,
    services: Services = Depends(get_services),
    identity: Identity = Depends(current_identity),
) -> SmartSessionView:
    """Copy one of the offered decks into the library."""
    record = _load(services, session_id, identity.user_id)
    engine = _engine(services, record.legend_id)
    proposal = engine.propose(
        _session_of(record, _declared(services, identity.user_id))
    )

    if payload.which == "conservative":
        chosen = proposal.conservative.deck if proposal.conservative else None
    elif payload.which == "free":
        chosen = proposal.free.deck if proposal.free else None
    else:
        chosen = proposal.floor
    if chosen is None:
        raise HTTPException(
            status_code=409,
            detail=f"There is no {payload.which!r} deck to accept in this session yet.",
        )

    legend = services.catalog.get(record.legend_id)
    deck_id = services.decks.save(
        Deck.make(
            name=payload.name or f"{legend.name if legend else record.legend_id} (Smart Decks)",
            format=chosen.format,
            legend_id=chosen.legend_id,
            champion_id=chosen.champion_id,
            main=chosen.main,
            runes=chosen.runes,
            battlefields=chosen.battlefields,
            sideboard=chosen.sideboard,
        ),
        user_id=identity.user_id,
    )
    services.smart_decks.mark_saved(session_id, user_id=identity.user_id, deck_id=deck_id)
    return _session_view(
        _load(services, session_id, identity.user_id),
        services,
        identity.user_id,
        with_proposal=False,
    )


@router.post("/sessions/{session_id}/save-collection", response_model=SaveCollectionResult)
def save_collection(
    session_id: str,
    payload: SaveCollectionRequest,
    services: Services = Depends(get_services),
    identity: Identity = Depends(current_identity),
) -> SaveCollectionResult:
    """Opt-in: write what the session learned into the collection.

    Never called implicitly. "I don't have this, for this deck, right now" is not the
    same claim as "I do not own this card", and someone answering quickly to get a deck
    should not have a permanent fact recorded on their behalf.

    Lower bounds are skipped by default for the reason the domain keeps them separate:
    "I have all six this deck wants" does not mean they own exactly six, and writing it
    as a count would understate a player holding twelve.
    """
    record = _load(services, session_id, identity.user_id)
    catalog = services.catalog

    written = copies = cleared = 0
    for card_id, qty in record.exact.items():
        card = catalog.get(card_id)
        printing = card.default_printing if card else None
        if printing is None:
            continue
        services.collections.set_quantity(
            user_id=identity.user_id,
            print_id=printing.print_id,
            card_id=card_id,
            qty=int(qty),
            record_zero=True,
        )
        if int(qty) > 0:
            written += 1
            copies += int(qty)
        else:
            # Keep an explicit zero, so a broad ownership shortcut cannot restore it
            # next session. It is still not an owned card in the collection count.
            cleared += 1

    return SaveCollectionResult(
        cards_written=written,
        copies_written=copies,
        cards_cleared=cleared,
        skipped_lower_bounds=len(record.at_least) if payload.exact_only else 0,
    )


@router.delete("/sessions/{session_id}", status_code=204, response_class=Response)
def delete_session(
    session_id: str,
    services: Services = Depends(get_services),
    identity: Identity = Depends(current_identity),
) -> Response:
    if not services.smart_decks.delete(session_id, user_id=identity.user_id):
        raise HTTPException(status_code=404, detail="No such wizard session.")
    return Response(status_code=204)
