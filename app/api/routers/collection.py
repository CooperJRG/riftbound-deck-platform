import csv
from datetime import datetime, timezone
from io import StringIO
import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from app.auth.dependencies import AuthContext, require_user
from app.core.rate_limits import limiter
from app.core.services import get_services
from app.domain.models import (
    CollectionCsvImportRequest,
    CollectionItemRequest,
    CollectionJsonImportRequest,
    CollectionResetRequest,
    CollectionSnapshot,
)
from app.domain.normalization import coerce_quantity

router = APIRouter(prefix="/api/collection", tags=["collection"])


def _snapshot(*, user_id: str) -> CollectionSnapshot:
    svc = get_services()
    cards = svc.storage.get_collection(user_id=user_id)
    in_use = svc.storage.get_collection_in_use(user_id=user_id)
    available = svc.storage.get_effective_collection(user_id=user_id)
    return CollectionSnapshot(
        cards=cards,
        total_unique_cards=len(cards),
        total_copies=sum(int(v) for v in cards.values()),
        in_use_cards=in_use,
        available_cards=available,
        total_in_use_copies=sum(int(v) for v in in_use.values()),
        total_available_copies=sum(int(v) for v in available.values()),
    )


def _parse_collection_csv(text: str) -> dict[str, int]:
    out: dict[str, int] = {}
    stream = StringIO(text)
    reader = csv.DictReader(stream)
    if not reader.fieldnames:
        return out
    for row in reader:
        if not isinstance(row, dict):
            continue
        title = str(
            row.get("card_name")
            or row.get("card")
            or row.get("name")
            or row.get("title")
            or ""
        ).strip()
        qty = coerce_quantity(
            row.get("total_quantity")
            or row.get("quantity")
            or row.get("qty")
            or row.get("count")
            or 0
        )
        if title and qty > 0:
            out[title] = out.get(title, 0) + qty
    return out


def _parse_collection_json(text: str) -> dict[str, int]:
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}") from exc

    src: dict[str, object] = {}
    if isinstance(raw, dict) and isinstance(raw.get("cards"), dict):
        src = dict(raw.get("cards") or {})
    elif isinstance(raw, dict):
        src = raw
    else:
        raise HTTPException(status_code=400, detail="Collection JSON must be an object.")

    out: dict[str, int] = {}
    for title, qty in src.items():
        clean = str(title or "").strip()
        count = coerce_quantity(qty)
        if clean and count > 0:
            out[clean] = out.get(clean, 0) + count
    return out


def _snapshot_export_payload(snapshot: CollectionSnapshot) -> dict:
    return {
        "exportedAt": datetime.now(timezone.utc).isoformat(),
        **snapshot.model_dump(by_alias=True),
    }


def _snapshot_to_csv(snapshot: CollectionSnapshot) -> str:
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["card_name", "total_quantity"])
    for title, qty in sorted(snapshot.cards.items(), key=lambda row: row[0].casefold()):
        writer.writerow([title, int(qty)])
    return output.getvalue()


@router.get("", response_model=CollectionSnapshot)
@limiter.limit("60/minute")
def get_collection(request: Request, auth: AuthContext = Depends(require_user)) -> CollectionSnapshot:
    return _snapshot(user_id=auth.user_id)


@router.put("/item", response_model=CollectionSnapshot)
@limiter.limit("30/minute")
def upsert_collection_item(request: Request, body: CollectionItemRequest, auth: AuthContext = Depends(require_user)) -> CollectionSnapshot:
    svc = get_services()
    svc.storage.set_collection_item(user_id=auth.user_id, card_title=body.card, quantity=body.quantity)
    return _snapshot(user_id=auth.user_id)


@router.post("/import-csv", response_model=CollectionSnapshot)
@limiter.limit("10/minute")
def import_collection_csv(request: Request, body: CollectionCsvImportRequest, auth: AuthContext = Depends(require_user)) -> CollectionSnapshot:
    svc = get_services()
    parsed = _parse_collection_csv(body.csv_text)
    svc.storage.upsert_collection(auth.user_id, parsed, replace_existing=body.replace_existing)
    return _snapshot(user_id=auth.user_id)


@router.post("/import-json", response_model=CollectionSnapshot)
@limiter.limit("10/minute")
def import_collection_json(request: Request, body: CollectionJsonImportRequest, auth: AuthContext = Depends(require_user)) -> CollectionSnapshot:
    svc = get_services()
    parsed = _parse_collection_json(body.json_text)
    svc.storage.upsert_collection(auth.user_id, parsed, replace_existing=body.replace_existing)
    return _snapshot(user_id=auth.user_id)


@router.get("/export")
@limiter.limit("60/minute")
def export_collection(
    request: Request,
    export_format: str = Query(default="json", alias="format", max_length=8),
    auth: AuthContext = Depends(require_user),
):
    snapshot = _snapshot(user_id=auth.user_id)
    fmt = str(export_format or "json").strip().lower()
    if fmt == "json":
        return _snapshot_export_payload(snapshot)
    if fmt == "csv":
        return PlainTextResponse(
            content=_snapshot_to_csv(snapshot),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="riftbound-collection.csv"'},
        )
    raise HTTPException(status_code=400, detail="Export format must be 'json' or 'csv'.")


@router.post("/reset")
@limiter.limit("10/minute")
def reset_collection(request: Request, body: CollectionResetRequest, auth: AuthContext = Depends(require_user)) -> dict:
    if str(body.confirm_phrase or "").strip().upper() != "RESET":
        raise HTTPException(status_code=400, detail="Reset blocked. Send confirmPhrase='RESET' to proceed.")
    svc = get_services()
    backup = _snapshot(user_id=auth.user_id) if body.create_backup else None
    svc.storage.clear_collection(user_id=auth.user_id)
    return {
        "reset": True,
        "snapshot": _snapshot(user_id=auth.user_id).model_dump(by_alias=True),
        "backup": backup.model_dump(by_alias=True) if backup is not None else None,
    }


@router.delete("", response_model=CollectionSnapshot)
@limiter.limit("10/minute")
def clear_collection(request: Request, confirm: bool = Query(default=False), auth: AuthContext = Depends(require_user)) -> CollectionSnapshot:
    if not confirm:
        raise HTTPException(status_code=400, detail="Set confirm=true to clear collection.")
    svc = get_services()
    svc.storage.clear_collection(user_id=auth.user_id)
    return _snapshot(user_id=auth.user_id)
