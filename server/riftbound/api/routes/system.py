"""Health, formats, and card-data provenance."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ...services import Services, get_services
from ..schemas import BundleView, FormatView, SourceHealthView

#: Bumped whenever a response gains a field the shipped UI relies on.
#:
#: The server serves `web/dist` from disk while its own routes are fixed at start-up, so
#: a rebuilt page routinely talks to a server that has not restarted. Left undetected
#: that arrives as a bare `Cannot read properties of undefined` from whichever field is
#: newest -- an error that says nothing about the actual problem and has now cost three
#: separate bug reports. The page compares this number against its own and says so.
#:
#: Raise it in the same commit that adds the field, and raise EXPECTED_API_CONTRACT in
#: `web/src/api/client.ts` with it. Forgetting is not a harmless omission: the card
#: trends added `archiveFrom` without a bump, so a stale server returned nothing for it,
#: the page read `undefined`, and "All time" quietly asked for the default ninety days
#: instead of the whole archive -- a wrong answer rather than an error.
#:
#: 2: repair.cards on the wizard.
#: 3: card trends, the archive span, and the server-resolved `range`.
#: 4: card power for readable previews and the plain-text deck export route.
API_CONTRACT = 5

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health")
def health(services: Services = Depends(get_services)) -> dict:
    manifest = services.bundle.manifest
    snapshot = services.meta
    return {
        "ok": True,
        "apiContract": API_CONTRACT,
        "mode": services.config.mode,
        "bundleId": manifest.bundle_id,
        "cardCount": manifest.card_count,
        "formats": sorted(services.bound_formats),
        "migrations": services.db.applied_migrations(),
        # Meta is optional; report its absence rather than failing.
        "metaSnapshotId": snapshot.manifest.snapshot_id if snapshot else "",
        "metaDeckCount": snapshot.manifest.deck_count if snapshot else 0,
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
