import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile

from app.auth.dependencies import AuthContext, require_user
from app.core.rate_limits import limiter
from app.core.services import get_services
from app.domain.analysis import analyze_collection_completion
from app.domain.eligibility import build_eligibility_snapshot
from app.domain.models import (
    CardView,
    DeckAnalyzeRequest,
    DeckLibraryBucketRequest,
    DeckEligibilityResponse,
    DeckVisibilityRequest,
    FormatProfileSummary,
    DeckImportRequest,
    DeckLibraryRow,
    DeckLibraryUpsertRequest,
    DeckPayload,
    DeckValidationRequest,
    DeckValidationResult,
)
from app.domain.normalization import canonicalize_titles, coerce_cards_map
from app.domain.validator import validate_deck
from app.infra.cards_repo import card_art_url

router = APIRouter(prefix="/api/decks", tags=["decks"])

_DECK_IMPORT_MAX_BYTES = 1024 * 1024



def _ensure_importable_deck_object(parsed: object) -> DeckPayload:
    allowed = {"name", "source", "format", "legendTitle", "chosenChampionTitle", "main", "runes", "battlefields", "sideboard"}
    if isinstance(parsed, dict) and "deck" in parsed and isinstance(parsed.get("deck"), dict):
        outer_unknown = sorted(k for k in parsed.keys() if k != "deck")
        if outer_unknown:
            raise HTTPException(status_code=400, detail=f"Unknown fields: {', '.join(outer_unknown)}")
        deck_obj = dict(parsed["deck"])
    elif isinstance(parsed, dict):
        deck_obj = dict(parsed)
    else:
        raise HTTPException(status_code=400, detail="Imported JSON must be an object.")
    unknown = sorted(key for key in deck_obj.keys() if key not in allowed)
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown deck fields: {', '.join(unknown)}")
    return DeckPayload.model_validate(deck_obj)


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


def card_to_view(card) -> CardView:
    return CardView(
        title=card.title,
        cardType=card.card_type,
        superType=card.super_type,
        domains=list(card.domains),
        championTags=list(card.champion_tags),
        cost=card.cost,
        might=card.might,
        isUnique=bool(card.is_unique),
        imageUrl=card_art_url(card),
        rarity=card.rarity,
        set=card.set_name,
        cardNumber=card.card_number,
        effect=card.effect,
        flavor=card.flavor,
        tags=list(card.tags),
        promo=bool(card.promo),
    )


@router.post("/validate", response_model=DeckValidationResult)
@limiter.limit("30/minute")
def validate_deck_endpoint(request: Request, body: DeckValidationRequest, _auth: AuthContext = Depends(require_user)) -> DeckValidationResult:
    svc = get_services()
    canonical = _canonicalize_deck(body.deck)
    return validate_deck(canonical, rules=svc.rules_for_format(canonical.format), cards=svc.cards)


@router.post("/analyze")
@limiter.limit("30/minute")
def analyze_deck_endpoint(request: Request, body: DeckAnalyzeRequest, auth: AuthContext = Depends(require_user)) -> dict:
    svc = get_services()
    canonical = _canonicalize_deck(body.deck)
    validation = validate_deck(canonical, rules=svc.rules_for_format(canonical.format), cards=svc.cards)
    collection = body.collection_override if body.collection_override is not None else svc.storage.get_effective_collection(user_id=auth.user_id)
    analysis = analyze_collection_completion(
        canonical,
        collection=collection,
        cards=svc.cards,
        unit_price_for_title=svc.prices.cheapest_price_for_title,
        buy_url_for_title=svc.prices.tcgplayer_search_url,
    )
    learned_replacements, win_condition_label = svc.auto_builder.suggest_replacements(deck=canonical, collection=collection)
    if learned_replacements:
        analysis.replacement_suggestions = learned_replacements
    if win_condition_label:
        analysis.win_condition_label = win_condition_label
    return {
        "deck": canonical.model_dump(by_alias=True),
        "validation": validation.model_dump(),
        "analysis": analysis.model_dump(by_alias=True),
    }


@router.get("/eligibility", response_model=DeckEligibilityResponse)
@limiter.limit("60/minute")
def deck_eligibility_endpoint(
    request: Request,
    format_name: str = Query(default="constructed", alias="format", max_length=40),
    legend_title: str = Query(default="", alias="legendTitle", max_length=200),
    query: str = Query(default="", max_length=120),
    limit: int = Query(default=400, ge=1, le=1200),
    _auth: AuthContext = Depends(require_user),
) -> DeckEligibilityResponse:
    svc = get_services()
    rules = svc.rules_for_format(format_name)
    snapshot = build_eligibility_snapshot(
        cards=svc.cards,
        rules=rules,
        legend_title=legend_title,
        query=query,
        limit=limit,
    )
    return DeckEligibilityResponse(
        legendTitle=snapshot.legend_title,
        legendDomains=list(snapshot.legend_domains),
        legends=[card_to_view(card) for card in snapshot.legends],
        champions=[card_to_view(card) for card in snapshot.champions],
        battlefields=[card_to_view(card) for card in snapshot.battlefields],
        runes=[card_to_view(card) for card in snapshot.runes],
        recommendedRunes=dict(snapshot.recommended_runes),
        mainDeckSize=snapshot.main_deck_size,
        runeDeckSize=snapshot.rune_deck_size,
        battlefieldCount=snapshot.battlefield_count,
        mainCopyLimit=snapshot.main_copy_limit,
        allowedMainCardTypes=list(snapshot.allowed_main_card_types),
        sideboardMax=snapshot.sideboard_max,
        allowedSideboardCardTypes=list(snapshot.allowed_sideboard_card_types),
    )


@router.get("/formats", response_model=list[FormatProfileSummary])
@limiter.limit("60/minute")
def list_supported_formats(request: Request, _auth: AuthContext = Depends(require_user)) -> list[FormatProfileSummary]:
    svc = get_services()
    default_key = str(svc.rules.format_name or "").strip().lower() or "constructed"
    out: list[FormatProfileSummary] = []
    for key, rules in svc.available_format_rules():
        out.append(
            FormatProfileSummary(
                format=key,
                description=rules.description,
                isDefault=key == default_key,
                mainDeckSize=rules.int_constraint("main_deck_size_exact", 40),
                runeDeckSize=rules.int_constraint("rune_count_exact", 12),
                battlefieldCount=rules.int_constraint("battlefield_count_exact", 3),
                sideboardMax=rules.int_constraint("sideboard_max", 8),
                mainCopyLimit=rules.int_constraint("main_copy_limit", 3),
            )
        )
    return out


@router.get("/library", response_model=list[DeckLibraryRow])
@limiter.limit("60/minute")
def list_library(
    request: Request,
    bucket: str | None = Query(default=None, max_length=16),
    query: str = Query(default="", max_length=120),
    auth: AuthContext = Depends(require_user),
) -> list[DeckLibraryRow]:
    svc = get_services()
    return svc.storage.list_decks(user_id=auth.user_id, bucket=bucket, query=query)


@router.get("/public", response_model=list[DeckLibraryRow])
@limiter.limit("60/minute")
def list_public_library(
    request: Request,
    query: str = Query(default="", max_length=120),
    format_name: str | None = Query(default=None, alias="format", max_length=40),
    sort_by: str = Query(default="updated", alias="sortBy", max_length=16),
    limit: int = Query(default=60, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    auth: AuthContext = Depends(require_user),
) -> list[DeckLibraryRow]:
    svc = get_services()
    clean_sort = sort_by if sort_by in ("updated", "likes", "name") else "updated"
    return svc.storage.list_public_decks(
        viewer_user_id=auth.user_id,
        query=query,
        format_name=format_name,
        limit=limit,
        offset=offset,
        sort_by=clean_sort,
    )


@router.get("/public/{deck_id}", response_model=DeckLibraryRow)
@limiter.limit("60/minute")
def get_public_library_deck(request: Request, deck_id: str, auth: AuthContext = Depends(require_user)) -> DeckLibraryRow:
    svc = get_services()
    row = svc.storage.get_public_deck(viewer_user_id=auth.user_id, deck_id=deck_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Public deck not found.")
    return row


@router.post("/public/{deck_id}/like")
@limiter.limit("60/minute")
def like_public_deck(request: Request, deck_id: str, auth: AuthContext = Depends(require_user)) -> dict:
    svc = get_services()
    row = svc.storage.get_public_deck(viewer_user_id=auth.user_id, deck_id=deck_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Public deck not found.")
    svc.storage.like_deck(user_id=auth.user_id, deck_id=deck_id)
    return {"liked": True}


@router.delete("/public/{deck_id}/like")
@limiter.limit("60/minute")
def unlike_public_deck(request: Request, deck_id: str, auth: AuthContext = Depends(require_user)) -> dict:
    svc = get_services()
    svc.storage.unlike_deck(user_id=auth.user_id, deck_id=deck_id)
    return {"liked": False}


@router.post("/public/{deck_id}/copy", response_model=DeckLibraryRow)
@limiter.limit("20/minute")
def copy_public_deck(request: Request, deck_id: str, auth: AuthContext = Depends(require_user)) -> DeckLibraryRow:
    svc = get_services()
    source_row = svc.storage.get_public_deck(viewer_user_id=auth.user_id, deck_id=deck_id)
    if source_row is None:
        raise HTTPException(status_code=404, detail="Public deck not found.")
    created = svc.storage.create_deck(
        user_id=auth.user_id,
        deck=source_row.deck,
        name=source_row.name,
        source="community",
        bucket="saved",
        visibility="private",
    )
    return created


@router.post("/library", response_model=DeckLibraryRow)
@limiter.limit("30/minute")
def add_library_deck(request: Request, body: DeckLibraryUpsertRequest, auth: AuthContext = Depends(require_user)) -> DeckLibraryRow:
    canonical = _canonicalize_deck(body.deck)
    svc = get_services()
    created = svc.storage.create_deck(
        user_id=auth.user_id,
        deck=canonical,
        name=body.name or canonical.name,
        source=body.source or canonical.source,
        bucket=body.bucket,
        visibility=body.visibility,
    )
    return created


@router.get("/library/{deck_id}", response_model=DeckLibraryRow)
@limiter.limit("60/minute")
def get_library_deck(request: Request, deck_id: str, auth: AuthContext = Depends(require_user)) -> DeckLibraryRow:
    svc = get_services()
    row = svc.storage.get_deck(user_id=auth.user_id, deck_id=deck_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Deck not found.")
    return row


@router.put("/library/{deck_id}", response_model=DeckLibraryRow)
@limiter.limit("30/minute")
def update_library_deck(request: Request, deck_id: str, body: DeckLibraryUpsertRequest, auth: AuthContext = Depends(require_user)) -> DeckLibraryRow:
    canonical = _canonicalize_deck(body.deck)
    svc = get_services()
    updated = svc.storage.update_deck(
        deck_id,
        user_id=auth.user_id,
        deck=canonical,
        name=body.name,
        source=body.source,
        bucket=body.bucket,
        visibility=body.visibility,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Deck not found.")
    return updated


@router.put("/library/{deck_id}/bucket", response_model=DeckLibraryRow)
@limiter.limit("30/minute")
def update_library_deck_bucket(request: Request, deck_id: str, body: DeckLibraryBucketRequest, auth: AuthContext = Depends(require_user)) -> DeckLibraryRow:
    svc = get_services()
    updated = svc.storage.set_deck_bucket(user_id=auth.user_id, deck_id=deck_id, bucket=body.bucket)
    if updated is None:
        raise HTTPException(status_code=404, detail="Deck not found.")
    return updated


@router.put("/library/{deck_id}/visibility", response_model=DeckLibraryRow)
@limiter.limit("30/minute")
def update_library_deck_visibility(request: Request, deck_id: str, body: DeckVisibilityRequest, auth: AuthContext = Depends(require_user)) -> DeckLibraryRow:
    svc = get_services()
    row = svc.storage.get_deck(user_id=auth.user_id, deck_id=deck_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Deck not found.")
    updated = svc.storage.update_deck(
        deck_id,
        user_id=auth.user_id,
        deck=row.deck,
        name=None,
        source=None,
        visibility=body.visibility,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Deck not found.")
    return updated


@router.delete("/library/{deck_id}")
@limiter.limit("30/minute")
def delete_library_deck(request: Request, deck_id: str, auth: AuthContext = Depends(require_user)) -> dict:
    svc = get_services()
    deleted = svc.storage.delete_deck(user_id=auth.user_id, deck_id=deck_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Deck not found.")
    return {"deleted": True}


@router.get("/library/{deck_id}/export")
@limiter.limit("60/minute")
def export_library_deck(request: Request, deck_id: str, auth: AuthContext = Depends(require_user)) -> dict:
    svc = get_services()
    row = svc.storage.get_deck(user_id=auth.user_id, deck_id=deck_id)
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
@limiter.limit("10/minute")
def import_library_deck(request: Request, body: DeckImportRequest, auth: AuthContext = Depends(require_user)) -> DeckLibraryRow:
    try:
        parsed = json.loads(body.raw_text)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}") from exc

    deck_payload = _ensure_importable_deck_object(parsed)
    canonical = _canonicalize_deck(deck_payload)
    svc = get_services()
    created = svc.storage.create_deck(
        user_id=auth.user_id,
        deck=canonical,
        name=body.name or canonical.name,
        source=body.source or canonical.source or "import",
        bucket=body.bucket,
        visibility=body.visibility,
    )
    return created


@router.post("/import-file", response_model=DeckLibraryRow)
@limiter.limit("10/minute")
async def import_library_deck_file(
    request: Request,
    file: UploadFile = File(...),
    name: str | None = Form(default=None),
    source: str | None = Form(default=None),
    bucket: str | None = Form(default=None),
    visibility: str | None = Form(default=None),
    auth: AuthContext = Depends(require_user),
) -> DeckLibraryRow:
    if not str(file.filename or "").lower().endswith(".json"):
        raise HTTPException(status_code=400, detail="Deck upload must be a .json file.")
    raw = await file.read()
    if len(raw) > _DECK_IMPORT_MAX_BYTES:
        raise HTTPException(status_code=413, detail="Deck upload exceeds the 1 MiB limit.")
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="Deck upload must be UTF-8 JSON.") from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}") from exc
    canonical = _canonicalize_deck(_ensure_importable_deck_object(parsed))
    svc = get_services()
    return svc.storage.create_deck(
        user_id=auth.user_id,
        deck=canonical,
        name=name or canonical.name,
        source=source or canonical.source or "upload",
        bucket=bucket,
        visibility=visibility,
    )
