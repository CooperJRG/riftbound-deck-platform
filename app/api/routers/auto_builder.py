from fastapi import APIRouter, Depends, Request, Response

from app.auth.dependencies import AuthContext, require_user
from app.core.rate_limits import limiter
from app.core.services import get_services
from app.domain.models import (
    AutoBuilderCompleteRequest,
    AutoBuilderRecommendationRequest,
    AutoBuilderStatus,
    WinConditionSummary,
)

router = APIRouter(prefix="/api/auto-builder", tags=["auto-builder"])


@router.get("/status", response_model=AutoBuilderStatus)
@limiter.limit("60/minute")
def auto_builder_status(request: Request, _auth: AuthContext = Depends(require_user)) -> AutoBuilderStatus:
    svc = get_services()
    payload = dict(svc.auto_builder.status())
    payload["modelDir"] = ""
    if payload.get("lastError"):
        payload["lastError"] = "Auto Builder is unavailable."
    return AutoBuilderStatus(**payload)


@router.get("/win-conditions", response_model=list[WinConditionSummary])
@limiter.limit("60/minute")
def auto_builder_win_conditions(request: Request, response: Response, _auth: AuthContext = Depends(require_user)) -> list[WinConditionSummary]:
    svc = get_services()
    response.headers["Cache-Control"] = "private, max-age=600"
    return [WinConditionSummary(**row) for row in svc.auto_builder.win_conditions()]


@router.post("/recommendations")
@limiter.limit("30/minute")
def auto_builder_recommendations(request: Request, body: AutoBuilderRecommendationRequest, auth: AuthContext = Depends(require_user)) -> dict:
    svc = get_services()
    collection = body.collection_override if body.collection_override is not None else svc.storage.get_effective_collection(user_id=auth.user_id)
    return svc.auto_builder.recommend(
        collection=collection,
        top=body.top,
        ranking_mode=body.ranking_mode,
        strategy_mode=body.strategy_mode,
        legend_title=body.legend_title,
        chosen_champion_title=body.chosen_champion_title,
        only_buildable=body.only_buildable,
        min_results=body.min_results,
        diversity_mode=body.diversity_mode,
    )


@router.post("/complete")
@limiter.limit("30/minute")
def auto_builder_complete(request: Request, body: AutoBuilderCompleteRequest, auth: AuthContext = Depends(require_user)) -> dict:
    svc = get_services()
    collection = body.collection_override if body.collection_override is not None else svc.storage.get_effective_collection(user_id=auth.user_id)
    return svc.auto_builder.complete(
        deck=body.deck,
        collection=collection,
        ranking_mode=body.ranking_mode,
        strategy_mode=body.strategy_mode,
    )
