"""The competitive meta, filtered through what the player can actually field.

Every deck is returned with three things attached:

* **provenance** — where it came from and what backs it, so a ranking can be argued with;
* **score** with its breakdown, for the same reason;
* **coverage** against the active availability profile — the number that matters to a
  casual player, because "3rd of 257" is only useful alongside "and you're four cards
  short of it".

That last join is the reason meta tracking earns its place here rather than being a link
to someone else's tier list.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from ...domain.availability import deck_coverage
from ...domain.meta import EVIDENCE_TIERS, MetaDeck, build_archetypes
from ...domain.meta_scoring import score_all, totals
from ...services import Services, get_services
from ..identity import Identity, current_identity
from ..schemas import (
    ArchetypeView,
    MetaDeckView,
    MetaStatusView,
    TournamentView,
)
from ..views import meta_deck_view, tournament_view

router = APIRouter(prefix="/api/meta", tags=["meta"])


def _require_meta(services: Services):
    snapshot = services.meta
    if snapshot is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "No meta snapshot has been built yet. Run: "
                "python -m riftbound.data.meta_pipeline build --promote"
            ),
        )
    return snapshot


@router.get("/status", response_model=MetaStatusView)
def meta_status(services: Services = Depends(get_services)) -> MetaStatusView:
    """Whether meta data exists, and how fresh it is. Never 503s — absence is an answer."""
    snapshot = services.meta
    if snapshot is None:
        return MetaStatusView(
            available=False,
            snapshot_id="",
            created_at="",
            deck_count=0,
            tournament_count=0,
            evidence_counts={},
            warnings=[],
        )
    m = snapshot.manifest
    return MetaStatusView(
        available=True,
        snapshot_id=m.snapshot_id,
        created_at=m.created_at,
        deck_count=m.deck_count,
        tournament_count=m.tournament_count,
        evidence_counts=dict(m.evidence_counts),
        warnings=list(m.warnings[:10]),
    )


@router.get("/tournaments", response_model=list[TournamentView])
def list_tournaments(
    limit: int = Query(default=30, ge=1, le=200),
    services: Services = Depends(get_services),
) -> list[TournamentView]:
    snapshot = _require_meta(services)
    return [tournament_view(t) for t in snapshot.tournaments[:limit]]


def _ranked(services: Services) -> tuple[list[MetaDeck], dict]:
    snapshot = _require_meta(services)
    decks = list(snapshot.decks)
    scores = score_all(decks)
    decks.sort(key=lambda d: scores[d.deck_id].total, reverse=True)
    return decks, scores


@router.get("/decks", response_model=list[MetaDeckView])
def list_meta_decks(
    archetype: str = Query(default="", max_length=120),
    evidence: str = Query(default="", max_length=32),
    buildable_only: bool = Query(default=False, alias="buildableOnly"),
    limit: int = Query(default=30, ge=1, le=200),
    services: Services = Depends(get_services),
    identity: Identity = Depends(current_identity),
) -> list[MetaDeckView]:
    """Ranked meta decks, each scored against what the player can field."""
    if evidence and evidence not in EVIDENCE_TIERS:
        raise HTTPException(
            status_code=400, detail=f"evidence must be one of {', '.join(EVIDENCE_TIERS)}"
        )
    decks, scores = _ranked(services)
    profile = services.availability.load(user_id=identity.user_id)
    catalog = services.catalog

    out: list[MetaDeckView] = []
    for deck in decks:
        if archetype and deck.archetype_id != archetype:
            continue
        if evidence and deck.provenance.evidence != evidence:
            continue
        coverage = deck_coverage(
            _deck_counts(deck), profile=profile, catalog=catalog
        )
        if buildable_only and not coverage.is_complete:
            continue
        out.append(meta_deck_view(deck, scores[deck.deck_id], coverage, catalog))
        if len(out) >= limit:
            break
    return out


@router.get("/archetypes", response_model=list[ArchetypeView])
def list_archetypes(
    limit: int = Query(default=20, ge=1, le=100),
    services: Services = Depends(get_services),
    identity: Identity = Depends(current_identity),
) -> list[ArchetypeView]:
    """What is winning, grouped by legend + champion."""
    snapshot = _require_meta(services)
    decks = list(snapshot.decks)
    scores = score_all(decks)
    archetypes = build_archetypes(decks, catalog=services.catalog, scores=totals(scores))
    profile = services.availability.load(user_id=identity.user_id)
    catalog = services.catalog

    out: list[ArchetypeView] = []
    for arch in archetypes[:limit]:
        best = arch.decks[0] if arch.decks else None
        coverage = (
            deck_coverage(_deck_counts(best), profile=profile, catalog=catalog)
            if best
            else None
        )
        out.append(
            ArchetypeView(
                archetype_id=arch.archetype_id,
                name=arch.name,
                legend_id=arch.legend_id,
                champion_id=arch.champion_id,
                deck_count=arch.deck_count,
                tournament_deck_count=arch.tournament_deck_count,
                best_placement=arch.best_placement,
                latest_date=arch.latest_date,
                score=round(arch.score, 4),
                best_deck=(
                    meta_deck_view(best, scores[best.deck_id], coverage, catalog)
                    if best and coverage
                    else None
                ),
            )
        )
    return out


@router.get("/decks/{deck_id}", response_model=MetaDeckView)
def get_meta_deck(
    deck_id: str,
    services: Services = Depends(get_services),
    identity: Identity = Depends(current_identity),
) -> MetaDeckView:
    decks, scores = _ranked(services)
    match = next((d for d in decks if d.deck_id == deck_id), None)
    if match is None:
        raise HTTPException(status_code=404, detail=f"No meta deck {deck_id!r}.")
    profile = services.availability.load(user_id=identity.user_id)
    coverage = deck_coverage(_deck_counts(match), profile=profile, catalog=services.catalog)
    return meta_deck_view(match, scores[match.deck_id], coverage, services.catalog)


@router.post("/decks/{deck_id}/import", status_code=201)
def import_meta_deck(
    deck_id: str,
    services: Services = Depends(get_services),
    identity: Identity = Depends(current_identity),
) -> dict:
    """Copy a meta deck into the player's own library, ready to edit.

    The copy records where it came from in its name, so a deck in the library is never
    mistaken for one the player built themselves.
    """
    snapshot = _require_meta(services)
    match = next((d for d in snapshot.decks if d.deck_id == deck_id), None)
    if match is None:
        raise HTTPException(status_code=404, detail=f"No meta deck {deck_id!r}.")
    copy = match.deck.with_meta(name=f"{match.deck.name} (imported)")
    new_id = services.decks.save(copy, user_id=identity.user_id)
    return {"deckId": new_id, "name": copy.name, "source": match.provenance.url}


def _deck_counts(deck: MetaDeck) -> dict[str, int]:
    """Every card a deck needs, across zones, for coverage accounting."""
    counts = dict(deck.deck.main)
    for card_id, qty in deck.deck.runes.items():
        counts[card_id] = counts.get(card_id, 0) + qty
    for card_id in deck.deck.battlefields:
        counts[card_id] = counts.get(card_id, 0) + 1
    if deck.deck.legend_id:
        counts[deck.deck.legend_id] = counts.get(deck.deck.legend_id, 0) + 1
    return counts
