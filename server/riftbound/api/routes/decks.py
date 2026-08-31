"""Deck building: validate, save, load, delete.

Validation always reports *both* legality (rules) and coverage (availability), so the
UI can distinguish "this deck is illegal" from "this deck is legal but you're missing
four cards" -- two different problems that v2 conflated.
"""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import PlainTextResponse

from ...config import ConfigError
from ...domain.availability import deck_coverage
from ...domain.deck import Deck
from ...domain.deck_analysis import nearest_field_match
from ...domain.export import export_deck, export_filename
from ...domain.field_plan import sideboard_plan
from ...domain.suggest import (
    battlefield_suggestions,
    champion_options,
    main_deck_suggestions,
    rune_suggestion,
    rune_suggestion_reason,
    sideboard_suggestions,
)
from ...domain.validator import validate
from ...services import Services, get_services
from ..identity import Identity, current_identity
from ..schemas import (
    BuildSuggestionsView,
    ChampionOptionView,
    DeckPayload,
    DeckSummaryView,
    DeckView,
    SuggestionView,
    ValidationView,
)
from ..views import deck_dict, deck_score_view, sideboard_plan_view, validation_view

router = APIRouter(prefix="/api/decks", tags=["decks"])

# Five cards remain the readable on-screen choice. The rest form a ranked reserve so
# rejecting one can promote its successor immediately instead of leaving a hole.
SUGGESTION_RESERVE = 20


def _to_deck(payload: DeckPayload) -> Deck:
    return Deck.make(
        name=payload.name,
        format=payload.format,
        legend_id=payload.legend_id,
        champion_id=payload.champion_id,
        main=payload.main,
        runes=payload.runes,
        battlefields=payload.battlefields,
        sideboard=payload.sideboard,
    )


def _validate(deck: Deck, services: Services, user_id: str) -> ValidationView:
    try:
        rules = services.rules_for(deck.format)
    except ConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    profile = services.availability.load(user_id=user_id)
    result = validate(deck, rules=rules, catalog=services.catalog)
    counts = dict(deck.main)
    for card_id in deck.battlefields:
        counts[card_id] = counts.get(card_id, 0) + 1
    for card_id, qty in deck.runes.items():
        counts[card_id] = counts.get(card_id, 0) + qty
    coverage = deck_coverage(counts, profile=profile, catalog=services.catalog)
    return validation_view(result, coverage, services.catalog)


@router.post("/validate", response_model=ValidationView)
def validate_deck(
    payload: DeckPayload,
    services: Services = Depends(get_services),
    identity: Identity = Depends(current_identity),
) -> ValidationView:
    return _validate(_to_deck(payload), services, identity.user_id)


@router.post("/export", response_class=PlainTextResponse)
def export_deck_text(
    payload: DeckPayload,
    services: Services = Depends(get_services),
) -> PlainTextResponse:
    """The deck as exchange-format text, ready to paste or save.

    Takes the deck in the body rather than reading a saved one by id, so a deck can be
    exported while it is still being built and has never been saved. Nothing about the
    result is per-user, so it does not ask for an identity.

    The filename rides along in ``Content-Disposition`` for callers that want to save
    rather than copy; a fetch for the clipboard ignores it.
    """
    deck = _to_deck(payload)
    return PlainTextResponse(
        export_deck(deck, services.catalog),
        headers={
            "Content-Disposition": f'attachment; filename="{export_filename(deck)}"'
        },
    )


@router.get("", response_model=list[DeckSummaryView])
def list_decks(
    services: Services = Depends(get_services),
    identity: Identity = Depends(current_identity),
) -> list[DeckSummaryView]:
    rows: list[DeckSummaryView] = []
    for summary in services.decks.list(user_id=identity.user_id):
        deck = services.decks.get(summary.deck_id, user_id=identity.user_id)
        score = services.deck_scoreboard.score(deck) if deck is not None else None
        rows.append(DeckSummaryView(
            deck_id=summary.deck_id, name=summary.name, format=summary.format,
            legend_id=summary.legend_id, champion_id=summary.champion_id,
            main_total=summary.main_total, created_at=summary.created_at,
            updated_at=summary.updated_at,
            score=deck_score_view(score) if score is not None else None,
        ))
    return rows


@router.post("", response_model=DeckView, status_code=201)
def create_deck(
    payload: DeckPayload,
    services: Services = Depends(get_services),
    identity: Identity = Depends(current_identity),
) -> DeckView:
    deck = _to_deck(payload)
    deck_id = services.decks.save(deck, user_id=identity.user_id)
    return DeckView(
        deck_id=deck_id,
        deck=deck_dict(deck),
        validation=_validate(deck, services, identity.user_id),
    )


@router.get("/{deck_id}", response_model=DeckView)
def get_deck(
    deck_id: str,
    services: Services = Depends(get_services),
    identity: Identity = Depends(current_identity),
) -> DeckView:
    deck = services.decks.get(deck_id, user_id=identity.user_id)
    if deck is None:
        raise HTTPException(status_code=404, detail="Deck not found.")
    return DeckView(
        deck_id=deck_id,
        deck=deck_dict(deck),
        validation=_validate(deck, services, identity.user_id),
    )


@router.put("/{deck_id}", response_model=DeckView)
def update_deck(
    deck_id: str,
    payload: DeckPayload,
    services: Services = Depends(get_services),
    identity: Identity = Depends(current_identity),
) -> DeckView:
    if services.decks.get(deck_id, user_id=identity.user_id) is None:
        raise HTTPException(status_code=404, detail="Deck not found.")
    deck = _to_deck(payload)
    services.decks.save(deck, user_id=identity.user_id, deck_id=deck_id)
    return DeckView(
        deck_id=deck_id,
        deck=deck_dict(deck),
        validation=_validate(deck, services, identity.user_id),
    )


@router.delete("/{deck_id}", status_code=204, response_class=Response)
def delete_deck(
    deck_id: str,
    services: Services = Depends(get_services),
    identity: Identity = Depends(current_identity),
) -> Response:
    if not services.decks.delete(deck_id, user_id=identity.user_id):
        raise HTTPException(status_code=404, detail="Deck not found.")
    return Response(status_code=204)


@router.post("/suggestions", response_model=BuildSuggestionsView)
def build_suggestions(
    payload: DeckPayload,
    services: Services = Depends(get_services),
    identity: Identity = Depends(current_identity),
) -> BuildSuggestionsView:
    """What to add next, for the deck as it currently stands.

    The manual builder is a search box and a deck, which is fine once you know the
    format and miserable before then. These are the statistics the wizard already runs
    on, pointed at a half-built deck: which champion the field nominates for this
    legend, which cards it plays beside the ones already chosen, which battlefields go
    with them, and a rune base that can actually cast the result.

    Everything in one response because everything depends on the same deck. Split across
    four endpoints they could be computed against four different versions of it and
    disagree about what the player is holding.
    """
    deck = _to_deck(payload)
    rules = services.rules_for(payload.format or "constructed")
    catalog = services.catalog
    runes = rune_suggestion(deck, catalog, rules)
    field_match = nearest_field_match(
        deck,
        services.meta.decks if services.meta is not None else (),
        catalog,
        services.deck_scores,
        rules=rules,
    )

    champions: list[ChampionOptionView] = []
    main: list[SuggestionView] = []
    battlefields: list[SuggestionView] = []
    sideboard: list[SuggestionView] = []

    if deck.legend_id and services.meta is not None:
        rates = {
            row.entity_id: (row.win_rate, row.shown)
            for row in services.champion_performance
        }
        champions = [
            ChampionOptionView(
                card_id=option.card_id, name=option.name, image_url=option.image_url,
                decks=option.decks, share=round(option.share, 4),
                win_rate=round(option.win_rate, 4), win_rate_shown=option.win_rate_shown,
                score=round(option.score, 1), summary=option.describe(),
            )
            for option in champion_options(
                deck.legend_id, services.meta.decks, catalog, rates
            )
        ]

    profile = services.legend_index.get(deck.legend_id) if deck.legend_id else None
    if profile is not None:
        main = [
            SuggestionView(
                card_id=s.card_id, name=s.name, image_url=s.image_url,
                copies=s.copies, reason=s.reason,
            )
            for s in main_deck_suggestions(
                deck, profile, catalog, rules, limit=SUGGESTION_RESERVE
            )
        ]
        battlefields = [
            SuggestionView(
                card_id=s.card_id, name=s.name, image_url=s.image_url,
                copies=s.copies, reason=s.reason,
            )
            for s in battlefield_suggestions(
                deck, profile, catalog, rules, limit=SUGGESTION_RESERVE
            )
        ]

    if deck.legend_id and services.meta is not None:
        sideboard = [
            SuggestionView(
                card_id=s.card_id, name=s.name, image_url=s.image_url,
                copies=s.copies, reason=s.reason,
            )
            for s in sideboard_suggestions(
                deck,
                services.meta.decks,
                services.deck_scores,
                catalog,
                rules,
                limit=SUGGESTION_RESERVE,
            )
        ]

    # What to prepare for after game one. Legend-level by construction: the matchup
    # table is legend against legend, so this depends on the legend chosen and not on
    # the forty cards under it -- which is why it is computed here rather than folded
    # into the card suggestions above, where it would imply a card-level claim the data
    # cannot support.
    plan_view = sideboard_plan_view(None, ())
    if deck.legend_id and services.matchups.available:
        outlook, plans = sideboard_plan(
            deck.legend_id,
            table=services.matchups,
            index=services.legend_index,
            catalog=catalog,
        )
        plan_view = sideboard_plan_view(outlook, plans)

    return BuildSuggestionsView(
        champions=champions,
        main=main,
        battlefields=battlefields,
        sideboard=sideboard,
        runes=runes,
        rune_reason=rune_suggestion_reason(deck, runes, catalog),
        field_match=asdict(field_match),
        deck_score=deck_score_view(services.deck_scoreboard.score(deck)),
        sideboard_plan=plan_view,
    )
