from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from app.auth.dependencies import require_admin
from app.core.services import get_services

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
def health() -> dict:
    svc = get_services()
    storage = svc.storage.schema_status()
    meta = svc.meta.status()
    cards_count = len(svc.cards.cards)
    cards_ok = cards_count > 0
    meta_ok = bool(meta.get("lastError") is None)
    ok = bool(storage.get("ok")) and cards_ok and meta_ok
    return {
        "ok": ok,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "checks": {
            "storage": {"ok": bool(storage.get("ok")), "backend": storage.get("backend"), "version": storage.get("actualVersion")},
            "cards": {"ok": cards_ok, "count": cards_count},
            "meta": {"ok": meta_ok, "indexedDecks": int(meta.get("indexedDecks") or 0), "lastRefreshedAt": meta.get("lastRefreshedAt")},
        },
    }


@router.get("/admin/health")
def admin_health(_auth=Depends(require_admin)) -> dict:
    svc = get_services()
    storage = svc.storage.schema_status()
    meta = svc.meta.status()
    auto_builder = svc.auto_builder.status()
    return {
        "ok": bool(storage.get("ok")) and not meta.get("lastError"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "checks": {
            "storage": storage,
            "cards": {
                "ok": len(svc.cards.cards) > 0,
                "count": len(svc.cards.cards),
                "cardsPath": str(svc.config.cards_path),
            },
            "meta": meta,
            "autoBuilder": auto_builder,
        },
    }
