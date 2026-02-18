from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Query

from app.core.services import get_services
from app.domain.analysis import analyze_collection_completion
from app.domain.eligibility import build_eligibility_snapshot
from app.domain.models import (
    CardView,
    DeckAnalyzeRequest,
    DeckLibraryBucketRequest,
    DeckEligibilityResponse,
    DeckImportRequest,
    DeckLibraryRow,
    DeckLibraryUpsertRequest,
    DeckPayload,
    DeckValidationRequest,
    DeckValidationResult,
)
from app.domain.normalization import canonicalize_titles, coerce_cards_map
from app.domain.validator import validate_deck

router = APIRouter(prefix="/api/decks", tags=["decks"])


def _canonicalize_deck(deck: DeckPayload) -> DeckPayload:
    svc = get_services()
    resolve_title = svc.cards.resolve_title
    main = canonicalize_titles(coerce_cards_map(deck.main), resolve_title=resolve_title)
    runes = canonicalize_titles(coerce_cards_map(deck.runes), resolve_title=resolve_title)
    sideboard = canonicalize_titles(coerce_cards_map(deck.sideboard), resolve_title=resolve_title)
    battlefields = [resolve_title(title) for title in deck.battlefields if str(title).strip()]
    return DeckPayload(
        name=deck.name,
        source=deck.source,
        format=deck.format,
        legendTitle=resolve_title(deck.legend_title),
        chosenChampionTitle=resolve_title(deck.chosen_champion_title),
        main=main,
        runes=runes,
        battlefields=battlefields,
        sideboard=sideboard,
    )


def _card_to_view(card) -> CardView:
    return CardView(
        title=card.title,
        cardType=card.card_type,
        superType=card.super_type,
        domains=list(card.domains),
        championTags=list(card.champion_tags),
        cost=card.cost,
        might=card.might,
        isUnique=bool(card.is_unique),
        imageUrl=card.image_url,
        rarity=card.rarity,
        set=card.set_name,
        cardNumber=card.card_number,
        effect=card.effect,
        flavor=card.flavor,
        tags=list(card.tags),
        promo=bool(card.promo),
    )


@router.post("/validate", response_model=DeckValidationResult)
def validate_deck_endpoint(body: DeckValidationRequest) -> DeckValidationResult:
    svc = get_services()
    canonical = _canonicalize_deck(body.deck)
    return validate_deck(canonical, rules=svc.rules, cards=svc.cards)


@router.post("/analyze")
def analyze_deck_endpoint(body: DeckAnalyzeRequest) -> dict:
    svc = get_services()
    canonical = _canonicalize_deck(body.deck)
    validation = validate_deck(canonical, rules=svc.rules, cards=svc.cards)
    collection = body.collection_override if body.collection_override is not None else svc.storage.get_effective_collection()
    analysis = analyze_collection_completion(canonical, collection=collection, cards=svc.cards)
    return {
        "deck": canonical.model_dump(by_alias=True),
        "validation": validation.model_dump(),
        "analysis": analysis.model_dump(),
    }


@router.get("/eligibility", response_model=DeckEligibilityResponse)
def deck_eligibility_endpoint(
    legend_title: str = Query(default="", alias="legendTitle", max_length=200),
    query: str = Query(default="", max_length=120),
    limit: int = Query(default=400, ge=1, le=1200),
) -> DeckEligibilityResponse:
    svc = get_services()
    snapshot = build_eligibility_snapshot(
        cards=svc.cards,
        rules=svc.rules,
        legend_title=legend_title,
        query=query,
        limit=limit,
    )
    return DeckEligibilityResponse(
        legendTitle=snapshot.legend_title,
        legendDomains=list(snapshot.legend_domains),
        legends=[_card_to_view(card) for card in snapshot.legends],
        champions=[_card_to_view(card) for card in snapshot.champions],
        battlefields=[_card_to_view(card) for card in snapshot.battlefields],
        runes=[_card_to_view(card) for card in snapshot.runes],
        recommendedRunes=dict(snapshot.recommended_runes),
        mainDeckSize=snapshot.main_deck_size,
        runeDeckSize=snapshot.rune_deck_size,
        battlefieldCount=snapshot.battlefield_count,
        mainCopyLimit=snapshot.main_copy_limit,
        allowedMainCardTypes=list(snapshot.allowed_main_card_types),
    )


@router.get("/library", response_model=list[DeckLibraryRow])
def list_library(bucket: str | None = Query(default=None, max_length=16)) -> list[DeckLibraryRow]:
    svc = get_services()
    return svc.storage.list_decks(bucket=bucket)


@router.post("/library", response_model=DeckLibraryRow)
def add_library_deck(body: DeckLibraryUpsertRequest) -> DeckLibraryRow:
    canonical = _canonicalize_deck(body.deck)
    svc = get_services()
    created = svc.storage.create_deck(
        deck=canonical,
        name=body.name or canonical.name,
        source=body.source or canonical.source,
        bucket=body.bucket,
    )
    return created


@router.get("/library/{deck_id}", response_model=DeckLibraryRow)
def get_library_deck(deck_id: str) -> DeckLibraryRow:
    svc = get_services()
    row = svc.storage.get_deck(deck_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Deck not found.")
    return row


@router.put("/library/{deck_id}", response_model=DeckLibraryRow)
def update_library_deck(deck_id: str, body: DeckLibraryUpsertRequest) -> DeckLibraryRow:
    canonical = _canonicalize_deck(body.deck)
    svc = get_services()
    updated = svc.storage.update_deck(
        deck_id,
        deck=canonical,
        name=body.name,
        source=body.source,
        bucket=body.bucket,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Deck not found.")
    return updated


@router.put("/library/{deck_id}/bucket", response_model=DeckLibraryRow)
def update_library_deck_bucket(deck_id: str, body: DeckLibraryBucketRequest) -> DeckLibraryRow:
    svc = get_services()
    updated = svc.storage.set_deck_bucket(deck_id, body.bucket)
    if updated is None:
        raise HTTPException(status_code=404, detail="Deck not found.")
    return updated


@router.delete("/library/{deck_id}")
def delete_library_deck(deck_id: str) -> dict:
    svc = get_services()
    deleted = svc.storage.delete_deck(deck_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Deck not found.")
    return {"deleted": True}


@router.get("/library/{deck_id}/export")
def export_library_deck(deck_id: str) -> dict:
    svc = get_services()
    row = svc.storage.get_deck(deck_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Deck not found.")
    return {
        "id": row.id,
        "name": row.name,
        "source": row.source,
        "format": row.format,
        "deck": row.deck.model_dump(by_alias=True),
    }


@router.post("/library/import", response_model=DeckLibraryRow)
def import_library_deck(body: DeckImportRequest) -> DeckLibraryRow:
    try:
        parsed = json.loads(body.raw_text)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}") from exc

    if isinstance(parsed, dict) and "deck" in parsed and isinstance(parsed.get("deck"), dict):
        deck_payload = DeckPayload.model_validate(parsed["deck"])
    elif isinstance(parsed, dict):
        deck_payload = DeckPayload.model_validate(parsed)
    else:
        raise HTTPException(status_code=400, detail="Imported JSON must be an object.")

    canonical = _canonicalize_deck(deck_payload)
    svc = get_services()
    created = svc.storage.create_deck(
        deck=canonical,
        name=body.name or canonical.name,
        source=body.source or canonical.source or "import",
        bucket=body.bucket,
    )
    return created
