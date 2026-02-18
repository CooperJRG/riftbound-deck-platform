from __future__ import annotations

import csv
from io import StringIO

from fastapi import APIRouter

from app.core.services import get_services
from app.domain.models import CollectionCsvImportRequest, CollectionItemRequest, CollectionSnapshot
from app.domain.normalization import coerce_quantity

router = APIRouter(prefix="/api/collection", tags=["collection"])


def _snapshot() -> CollectionSnapshot:
    svc = get_services()
    cards = svc.storage.get_collection()
    in_use = svc.storage.get_collection_in_use()
    available = svc.storage.get_effective_collection()
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


@router.get("", response_model=CollectionSnapshot)
def get_collection() -> CollectionSnapshot:
    return _snapshot()


@router.put("/item", response_model=CollectionSnapshot)
def upsert_collection_item(body: CollectionItemRequest) -> CollectionSnapshot:
    svc = get_services()
    svc.storage.set_collection_item(card_title=body.card, quantity=body.quantity)
    return _snapshot()


@router.post("/import-csv", response_model=CollectionSnapshot)
def import_collection_csv(body: CollectionCsvImportRequest) -> CollectionSnapshot:
    svc = get_services()
    parsed = _parse_collection_csv(body.csv_text)
    svc.storage.upsert_collection(parsed, replace_existing=body.replace_existing)
    return _snapshot()


@router.delete("", response_model=CollectionSnapshot)
def clear_collection() -> CollectionSnapshot:
    svc = get_services()
    svc.storage.clear_collection()
    return _snapshot()
