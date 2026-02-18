from __future__ import annotations

from dataclasses import dataclass
from fastapi import APIRouter, Query

from app.core.services import get_services
from app.domain.normalization import normalize_card_key
from app.domain.models import MetaDeckSummary

router = APIRouter(prefix="/api/meta", tags=["meta"])

_CANDIDATE_POOL_MIN = 5000
_CANDIDATE_POOL_MAX = 20000
_CANDIDATE_POOL_SCALE = 50


@dataclass
class _MetaRankRow:
    source: str
    deck_id: str
    deck_name: str
    deck_url: str
    meta_score: float | None
    deck_price: float | None
    views: float | None
    likes: int | None
    age_days: float | None
    leader_title: str
    deck: object
    is_buildable: bool | None
    completion_pct: float | None
    missing_copies: int | None
    missing_unique_cards: int | None
    recommendation_score: float | None


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _normalize_meta_score(score: float | None) -> float:
    return _clamp(float(score or 0.0), 0.0, 40.0)


def _recommendation_score(
    *,
    completion_pct: float,
    missing_copies: int,
    missing_unique_cards: int,
    meta_score: float | None,
    is_buildable: bool,
) -> float:
    # Mirror legacy riftbound/deck_matcher scoring so recommendations stay consistent.
    meta = _normalize_meta_score(meta_score)
    completion = _clamp(float(completion_pct), 0.0, 100.0) / 100.0
    meta_scaled = meta * (0.35 + 0.65 * completion)
    score = (
        2.3 * meta_scaled
        + 9.0 * completion
        - 1.7 * float(max(0, int(missing_copies)))
        - 0.55 * float(max(0, int(missing_unique_cards)))
        + (0.75 if is_buildable else 0.0)
    )
    return round(score, 4)


def _default_recommendation_without_collection(meta_score: float | None) -> float:
    # Keep ordering stable when collection context is disabled.
    return _recommendation_score(
        completion_pct=50.0,
        missing_copies=20,
        missing_unique_cards=8,
        meta_score=meta_score,
        is_buildable=False,
    )


def _candidate_pool_limit(requested_limit: int) -> int:
    return max(
        _CANDIDATE_POOL_MIN,
        min(_CANDIDATE_POOL_MAX, max(1, int(requested_limit)) * _CANDIDATE_POOL_SCALE),
    )


def _sort_meta_rows(rows: list, *, sort_by: str, sort_dir: str) -> list:
    key = str(sort_by or "").strip().lower()
    direction = str(sort_dir or "").strip().lower()
    desc = direction != "asc"

    if key == "price":
        if desc:
            return sorted(
                rows,
                key=lambda row: (
                    row.deck_price is None,
                    -float(row.deck_price or 0.0),
                    -float(row.recommendation_score or 0.0),
                ),
            )
        return sorted(
            rows,
            key=lambda row: (
                row.deck_price is None,
                float(row.deck_price or 0.0),
                -float(row.recommendation_score or 0.0),
            ),
        )

    if key == "meta":
        return sorted(
            rows,
            key=lambda row: (
                _normalize_meta_score(row.meta_score),
                float(row.recommendation_score or 0.0),
                float(row.views or 0.0),
            ),
            reverse=desc,
        )

    if key == "buildability":
        if desc:
            return sorted(
                rows,
                key=lambda row: (
                    -(1 if row.is_buildable else 0),
                    int(row.missing_copies or 0),
                    int(row.missing_unique_cards or 0),
                    -float(row.completion_pct or 0.0),
                    -float(row.recommendation_score or 0.0),
                    row.deck_name.lower(),
                ),
            )
        return sorted(
            rows,
            key=lambda row: (
                1 if row.is_buildable else 0,
                -int(row.missing_copies or 0),
                -int(row.missing_unique_cards or 0),
                float(row.completion_pct or 0.0),
                float(row.recommendation_score or 0.0),
                row.deck_name.lower(),
            ),
        )

    # Default: recommendation score
    if desc:
        return sorted(
            rows,
            key=lambda row: (
                -float(row.recommendation_score or 0.0),
                int(row.missing_copies or 0),
                int(row.missing_unique_cards or 0),
                -float(row.completion_pct or 0.0),
                -_normalize_meta_score(row.meta_score),
                -float(row.views or 0.0),
                -int(row.likes or 0),
                row.deck_name.lower(),
            ),
        )
    return sorted(
        rows,
        key=lambda row: (
            float(row.recommendation_score or 0.0),
            -int(row.missing_copies or 0),
            -int(row.missing_unique_cards or 0),
            float(row.completion_pct or 0.0),
            _normalize_meta_score(row.meta_score),
            float(row.views or 0.0),
            int(row.likes or 0),
            row.deck_name.lower(),
        ),
    )


def _collection_by_key(cards_map: dict[str, int]) -> dict[str, int]:
    out: dict[str, int] = {}
    for title, qty in cards_map.items():
        key = normalize_card_key(title)
        if not key:
            continue
        out[key] = out.get(key, 0) + max(0, int(qty))
    return out


def _collection_metrics_for_entry(
    *,
    requirements_by_key: tuple[tuple[str, int], ...],
    total_required: int,
    collection_by_key: dict[str, int],
) -> tuple[bool, float, int, int]:
    required_total = max(0, int(total_required))
    if required_total <= 0:
        return True, 100.0, 0, 0

    owned_for_deck = 0
    missing_copies = 0
    missing_unique_cards = 0
    for key, qty in requirements_by_key:
        required = max(0, int(qty))
        if required <= 0:
            continue
        owned = max(0, int(collection_by_key.get(key, 0)))
        owned_for_deck += min(required, owned)
        missing = max(0, required - owned)
        if missing > 0:
            missing_copies += missing
            missing_unique_cards += 1

    completion_pct = round((owned_for_deck / float(required_total)) * 100.0, 2)
    return missing_copies == 0, completion_pct, missing_copies, missing_unique_cards


@router.get("/decks", response_model=list[MetaDeckSummary])
def list_meta_decks(
    query: str = Query(default="", max_length=120),
    sort_by: str = Query(default="recommendation", alias="sortBy", max_length=40),
    sort_dir: str = Query(default="desc", alias="sortDir", max_length=8),
    include_collection: bool = Query(default=True, alias="includeCollection"),
    limit: int = Query(default=60, ge=1, le=300),
    offset: int = Query(default=0, ge=0),
) -> list[MetaDeckSummary]:
    svc = get_services()
    # Score/sort against a large pool first, then return requested window.
    entries = svc.meta.search_entries(query=query, limit=_candidate_pool_limit(limit), offset=0)
    rows: list[_MetaRankRow] = []

    if include_collection:
        collection_by_key = _collection_by_key(svc.storage.get_effective_collection())
        for entry in entries:
            is_buildable, completion_pct, missing_copies, missing_unique_cards = _collection_metrics_for_entry(
                requirements_by_key=entry.requirements_by_key,
                total_required=entry.total_required,
                collection_by_key=collection_by_key,
            )
            rows.append(
                _MetaRankRow(
                    source=entry.source,
                    deck_id=entry.deck_id,
                    deck_name=entry.deck_name,
                    deck_url=entry.deck_url,
                    meta_score=entry.meta_score,
                    deck_price=entry.deck_price,
                    views=entry.views,
                    likes=entry.likes,
                    age_days=entry.age_days,
                    leader_title=entry.leader_title,
                    deck=entry.deck,
                    is_buildable=is_buildable,
                    completion_pct=completion_pct,
                    missing_copies=missing_copies,
                    missing_unique_cards=missing_unique_cards,
                    recommendation_score=_recommendation_score(
                        completion_pct=completion_pct,
                        missing_copies=missing_copies,
                        missing_unique_cards=missing_unique_cards,
                        meta_score=entry.meta_score,
                        is_buildable=is_buildable,
                    ),
                )
            )
    else:
        for entry in entries:
            rows.append(
                _MetaRankRow(
                    source=entry.source,
                    deck_id=entry.deck_id,
                    deck_name=entry.deck_name,
                    deck_url=entry.deck_url,
                    meta_score=entry.meta_score,
                    deck_price=entry.deck_price,
                    views=entry.views,
                    likes=entry.likes,
                    age_days=entry.age_days,
                    leader_title=entry.leader_title,
                    deck=entry.deck,
                    is_buildable=None,
                    completion_pct=None,
                    missing_copies=None,
                    missing_unique_cards=None,
                    recommendation_score=_default_recommendation_without_collection(entry.meta_score),
                )
            )

    ranked = _sort_meta_rows(rows, sort_by=sort_by, sort_dir=sort_dir)
    start = max(0, int(offset))
    end = start + max(1, int(limit))
    return [
        MetaDeckSummary(
            source=row.source,
            deckId=row.deck_id,
            deckName=row.deck_name,
            deckUrl=row.deck_url,
            metaScore=row.meta_score,
            deckPrice=row.deck_price,
            views=row.views,
            likes=row.likes,
            ageDays=row.age_days,
            leaderTitle=row.leader_title,
            isBuildable=row.is_buildable,
            completionPct=row.completion_pct,
            missingCopies=row.missing_copies,
            missingUniqueCards=row.missing_unique_cards,
            recommendationScore=row.recommendation_score,
            deck=row.deck,
        )
        for row in ranked[start:end]
    ]
