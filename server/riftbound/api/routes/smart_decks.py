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
from ..views import deck_dict, meta_deck_view, repair_view, requirement_row

router = APIRouter(prefix="/api/smart-decks", tags=["smart-decks"])

#: How many of a legend's most-played cards to weigh when estimating familiarity.
FAMILIARITY_DEPTH = 20

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


def _session_of(record: WizardSessionRecord) -> Session:
    return Session(
        legend_id=record.legend_id,
        knowledge=Knowledge(exact=dict(record.exact), at_least=dict(record.at_least)),
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
    return DeckScoreView(
        meta=round(score.meta, 1),
        champion=round(score.champion, 1),
        strength=round(score.strength, 3),
        scored=score.scored,
        summary=score.describe(),
    )


def _floor_view(deck: Deck | None, engine: Engine, score=None) -> FloorView | None:
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
    )


def _proposal_view(
    proposal: Proposal, session: Session, engine: Engine, services: Services, user_id: str
) -> ProposalView:
    catalog = services.catalog
    knowledge = session.knowledge
    view = ProposalView(
        phase=proposal.phase,
        reason=proposal.reason,
        round=session.rounds + session.checklists,
        floor=_floor_view(proposal.floor, engine, proposal.floor_score),
        chosen=proposal.chosen,
        deck_score=_score_view(proposal.deck_score),
        feasibility=proposal.feasibility.describe() if proposal.feasibility else "",
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
) -> SmartSessionView:
    legend = services.catalog.get(record.legend_id)
    session = _session_of(record)
    proposal = None
    if with_proposal:
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
    )


# -- legends ------------------------------------------------------------------


@router.get("/legends", response_model=list[LegendChoiceView])
def list_legends(
    services: Services = Depends(get_services),
    identity: Identity = Depends(current_identity),
) -> list[LegendChoiceView]:
    """Legends the wizard can build for, strongest first.

    ``familiarity`` is advisory and never a filter. The point of the wizard is to find
    out what someone can build; pre-judging it from a collection they may not have
    entered would reintroduce exactly the barrier the two-mode design removes.
    """
    catalog = services.catalog
    owned = services.collections.owned_by_card(user_id=identity.user_id)
    scores = services.deck_scores

    tournament_counts: dict[str, int] = {}
    if services.meta is not None:
        for deck in services.meta.decks:
            if deck.provenance.evidence.startswith("tournament"):
                key = deck.deck.legend_id
                tournament_counts[key] = tournament_counts.get(key, 0) + 1

    out: list[LegendChoiceView] = []
    for legend_id, profile in services.legend_index.profiles.items():
        card = catalog.get(legend_id)
        if card is None:
            continue
        top = sorted(profile.play_rate, key=lambda c: -profile.play_rate[c])
        top = top[:FAMILIARITY_DEPTH]
        familiarity = (
            sum(1 for c in top if owned.get(c, 0) > 0) / len(top) if top and owned else 0.0
        )
        best = max(
            (scores.get(d, 0.0) for c in profile.clusters for d in c.deck_ids), default=0.0
        )
        out.append(
            LegendChoiceView(
                legend_id=legend_id,
                name=card.name,
                domains=list(card.domains),
                image_url=card.image_url,
                era_id=profile.era_id,
                deck_count=profile.deck_count,
                tournament_deck_count=tournament_counts.get(legend_id, 0),
                best_score=best,
                familiarity=familiarity,
            )
        )
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
    session = _session_of(record)

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

    services.smart_decks.record_round(
        session_id,
        user_id=identity.user_id,
        kind=kind,
        deck_id=payload.deck_id,
        answers=payload.have,
        exact=dict(updated.knowledge.exact),
        at_least=dict(updated.knowledge.at_least),
        phase=engine.propose(updated).phase,
        checklists=updated.checklists,
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
    proposal = engine.propose(_session_of(record))

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
        )
        if int(qty) > 0:
            written += 1
            copies += int(qty)
        else:
            # A zero is a real answer, so it is written -- but writing it removes the
            # row, so counting it as a card "written" would report a number the
            # collection cannot show back.
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
