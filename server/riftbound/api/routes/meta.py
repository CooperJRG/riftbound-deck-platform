"""Health, formats, and card-data provenance."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ...services import Services, get_services
from ..schemas import BundleView, FormatView, SourceHealthView

router = APIRouter(prefix="/api", tags=["meta"])


@router.get("/health")
def health(services: Services = Depends(get_services)) -> dict:
    manifest = services.bundle.manifest
    return {
        "ok": True,
        "mode": services.config.mode,
        "bundleId": manifest.bundle_id,
        "cardCount": manifest.card_count,
        "formats": sorted(services.bound_formats),
        "migrations": services.db.applied_migrations(),
    }


@router.get("/formats", response_model=list[FormatView])
def list_formats(services: Services = Depends(get_services)) -> list[FormatView]:
    return [
        FormatView(
            format=name,
            description=rules.rules.description,
            constraints=dict(rules.rules.constraints),
            banned_card_ids=sorted(rules.banned_card_ids),
        )
        for name, rules in sorted(services.bound_formats.items())
    ]


@router.get("/data/bundle", response_model=BundleView)
def bundle_info(services: Services = Depends(get_services)) -> BundleView:
    """Which card data this server is serving, and how healthy its sources were."""
    m = services.bundle.manifest
    return BundleView(
        bundle_id=m.bundle_id,
        created_at=m.created_at,
        card_count=m.card_count,
        printing_count=m.printing_count,
        set_codes=list(m.set_codes),
        sources=[
            SourceHealthView(
                name=s.name, ok=s.ok, fetched=s.fetched, accepted=s.accepted, error=s.error
            )
            for s in m.sources
        ],
        warnings=list(m.warnings),
    )
