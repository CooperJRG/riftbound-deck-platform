from __future__ import annotations

from dataclasses import dataclass
import subprocess
import sys

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from app.auth.dependencies import AuthContext, require_admin, require_user
from app.core.rate_limits import limiter
from app.core.services import get_services
from app.domain.meta_scoring import (
    collection_neutral_recommendation_score,
    deck_competitive_rank_score,
    deck_legend_meta_rank_score,
    deck_meta_sort_score,
    normalize_meta_score,
    recency_sort_bonus,
)
from app.domain.normalization import normalize_card_key
from app.domain.models import MetaDeckSummary, MetaIndexStatus

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
    competitive_score: float | None
    win_condition_id: int | None
    win_condition_label: str


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _recommendation_score(
    *,
    completion_pct: float,
    missing_copies: int,
    missing_unique_cards: int,
    meta_score: float | None,
    is_buildable: bool,
    age_days: float | None = None,
) -> float:
    # Mirror legacy riftbound/deck_matcher scoring so recommendations stay consistent.
    meta = normalize_meta_score(meta_score)
    completion = _clamp(float(completion_pct), 0.0, 100.0) / 100.0
    meta_scaled = meta * (0.35 + 0.65 * completion)
    score = (
        2.3 * meta_scaled
        + 9.0 * completion
        - 1.7 * float(max(0, int(missing_copies)))
        - 0.55 * float(max(0, int(missing_unique_cards)))
        + (0.75 if is_buildable else 0.0)
        + recency_sort_bonus(age_days)
    )
    return round(score, 4)


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
                    -normalize_meta_score(row.meta_score),
                    -float(row.views or 0.0),
                ),
            )
        return sorted(
            rows,
            key=lambda row: (
                row.deck_price is None,
                float(row.deck_price or 0.0),
                normalize_meta_score(row.meta_score),
                float(row.views or 0.0),
            ),
        )

    if key == "meta":
        return sorted(
            rows,
            key=lambda row: (
                deck_legend_meta_rank_score(row.leader_title),
                normalize_meta_score(row.meta_score),
                -float(row.age_days if row.age_days is not None else 10_000.0),
                float(row.views or 0.0),
                int(row.likes or 0),
                row.deck_name.lower(),
            ),
            reverse=desc,
        )

    if key == "recent":
        if desc:
            return sorted(
                rows,
                key=lambda row: (
                    row.age_days is None,
                    float(row.age_days if row.age_days is not None else 10_000.0),
                    -deck_meta_sort_score(
                        leader_title=row.leader_title,
                        meta_score=row.meta_score,
                        age_days=row.age_days,
                        views=row.views,
                    ),
                    -float(row.views or 0.0),
                ),
            )
        return sorted(
            rows,
            key=lambda row: (
                row.age_days is None,
                -float(row.age_days if row.age_days is not None else -1.0),
                deck_meta_sort_score(
                    leader_title=row.leader_title,
                    meta_score=row.meta_score,
                    age_days=row.age_days,
                    views=row.views,
                ),
                float(row.views or 0.0),
            ),
        )
    if key == "competitive":
        return sorted(
            rows,
            key=lambda row: (
                float(row.competitive_score or 0.0),
                normalize_meta_score(row.meta_score),
                -float(row.age_days if row.age_days is not None else 10_000.0),
                float(row.views or 0.0),
                row.deck_name.lower(),
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
                -normalize_meta_score(row.meta_score),
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
            normalize_meta_score(row.meta_score),
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
@limiter.limit("60/minute")
def list_meta_decks(
    request: Request,
    query: str = Query(default="", max_length=120),
    sort_by: str = Query(default="recommendation", alias="sortBy", max_length=40),
    sort_dir: str = Query(default="desc", alias="sortDir", max_length=8),
    include_collection: bool = Query(default=True, alias="includeCollection"),
    limit: int = Query(default=60, ge=1, le=300),
    offset: int = Query(default=0, ge=0),
    auth: AuthContext = Depends(require_user),
) -> list[MetaDeckSummary]:
    svc = get_services()
    # Score/sort against a large pool first, then return requested window.
    entries = svc.meta.search_entries(query=query, limit=_candidate_pool_limit(limit), offset=0)
    rows: list[_MetaRankRow] = []

    collection_by_key = (
        _collection_by_key(svc.storage.get_effective_collection(user_id=auth.user_id))
        if include_collection
        else {}
    )
    for entry in entries:
        annotation = svc.auto_builder.annotation_for_entry(entry)
        profile_competitive = float(annotation.get("competitiveScore") or 0.0) if annotation else None
        competitive_score = deck_competitive_rank_score(
            leader_title=entry.leader_title,
            meta_score=entry.meta_score,
            age_days=entry.age_days,
            views=entry.views,
            profile_competitive=profile_competitive,
        )
        if include_collection:
            is_buildable, completion_pct, missing_copies, missing_unique_cards = _collection_metrics_for_entry(
                requirements_by_key=entry.requirements_by_key,
                total_required=entry.total_required,
                collection_by_key=collection_by_key,
            )
            rec_score = _recommendation_score(
                completion_pct=completion_pct,
                missing_copies=missing_copies,
                missing_unique_cards=missing_unique_cards,
                meta_score=entry.meta_score,
                is_buildable=is_buildable,
                age_days=entry.age_days,
            )
        else:
            is_buildable = completion_pct = missing_copies = missing_unique_cards = None
            rec_score = collection_neutral_recommendation_score(
                leader_title=entry.leader_title,
                meta_score=entry.meta_score,
                age_days=entry.age_days,
                views=entry.views,
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
                recommendation_score=rec_score,
                competitive_score=competitive_score,
                win_condition_id=int(annotation.get("winConditionId") or 0) if annotation else None,
                win_condition_label=str(annotation.get("winConditionLabel") or "") if annotation else "",
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
            recommendationScore=row.recommendation_score if include_collection else None,
            competitiveScore=row.competitive_score,
            winConditionId=row.win_condition_id,
            winConditionLabel=row.win_condition_label,
            deck=row.deck,
        )
        for row in ranked[start:end]
    ]


@router.get("/status", response_model=MetaIndexStatus)
@limiter.limit("60/minute")
def meta_index_status(request: Request, response: Response, _auth: AuthContext = Depends(require_user)) -> MetaIndexStatus:
    svc = get_services()
    payload = dict(svc.meta.status())
    payload["sourcePath"] = ""
    payload["lastError"] = None
    response.headers["Cache-Control"] = "private, max-age=60"
    return MetaIndexStatus(**payload)


@router.post("/refresh", response_model=MetaIndexStatus)
@limiter.limit("5/hour")
def refresh_meta_index(request: Request, _auth=Depends(require_admin)) -> MetaIndexStatus:
    svc = get_services()
    cfg = svc.config
    script = cfg.meta_refresh_script_path
    if script.is_file():
        command = [
            sys.executable,
            str(script),
            "--cards",
            str(cfg.cards_path),
            "--cache-dir",
            str(cfg.deck_sources_cache_dir),
            "--out-json",
            str(cfg.meta_index_path),
            "--out-csv",
            str(cfg.meta_index_csv_path),
            "--out-prices-json",
            str(cfg.base_card_prices_json_path),
            "--out-prices-csv",
            str(cfg.base_card_prices_csv_path),
            "--rules-profile",
            str(cfg.rules_profile_path),
            "--auto-builder-dir",
            str(cfg.auto_builder_dir),
            "--auto-builder-epochs",
            str(cfg.auto_builder_epochs),
            "--skip-auto-builder",
        ]
        command.extend(cfg.meta_refresh_extra_args)
        try:
            completed = subprocess.run(
                command,
                cwd=str(cfg.workspace_root),
                capture_output=True,
                text=True,
                timeout=max(60, int(cfg.meta_auto_refresh_timeout_sec)),
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise HTTPException(status_code=504, detail="Meta ingest timed out.") from exc
        if completed.returncode != 0:
            tail = (completed.stderr or completed.stdout or "").strip()[-800:]
            raise HTTPException(
                status_code=500,
                detail=f"Meta ingest failed (exit {completed.returncode}). {tail}",
            )
        try:
            svc.prices.refresh(force=True)
        except Exception:
            pass
        if svc.config.auto_builder_enabled:
            try:
                svc.auto_builder.refresh(force=True)
            except Exception:
                pass
    return MetaIndexStatus(**svc.meta.refresh())
