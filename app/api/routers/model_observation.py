from fastapi import APIRouter, Depends, HTTPException, Request

from app.auth.dependencies import require_admin
from app.core.rate_limits import limiter
from app.core.services import get_services
from app.domain.models import (
    ModelObservationOverview,
    ModelObservationTrainingRequest,
    ModelTrainingStatus,
    ModelVersionActionRequest,
    ModelVersionSummary,
)

router = APIRouter(prefix="/api/model-observation", tags=["model-observation"])


@router.get("/overview", response_model=ModelObservationOverview)
@limiter.limit("60/minute")
def model_observation_overview(request: Request, _auth=Depends(require_admin)) -> ModelObservationOverview:
    svc = get_services()
    return ModelObservationOverview(**svc.model_observation.overview())


@router.get("/training", response_model=ModelTrainingStatus)
@limiter.limit("60/minute")
def model_observation_training_status(request: Request, _auth=Depends(require_admin)) -> ModelTrainingStatus:
    svc = get_services()
    return ModelTrainingStatus(**svc.model_observation.training_status())


@router.post("/training", response_model=ModelTrainingStatus)
@limiter.limit("5/hour")
def model_observation_start_training(request: Request, body: ModelObservationTrainingRequest, _auth=Depends(require_admin)) -> ModelTrainingStatus:
    svc = get_services()
    try:
        payload = svc.model_observation.start_training(body.model_dump(by_alias=True))
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ModelTrainingStatus(**payload)


@router.get("/models", response_model=list[ModelVersionSummary])
@limiter.limit("60/minute")
def model_observation_models(request: Request, _auth=Depends(require_admin)) -> list[ModelVersionSummary]:
    svc = get_services()
    return [ModelVersionSummary(**row) for row in svc.model_observation.list_models()]


@router.post("/models/snapshot", response_model=ModelVersionSummary)
@limiter.limit("5/hour")
def model_observation_snapshot(request: Request, body: ModelVersionActionRequest, _auth=Depends(require_admin)) -> ModelVersionSummary:
    svc = get_services()
    try:
        payload = svc.model_observation.snapshot_production(label=body.label)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ModelVersionSummary(**payload)


@router.post("/models/{model_id}/promote", response_model=ModelVersionSummary)
@limiter.limit("5/hour")
def model_observation_promote(request: Request, model_id: str, _auth=Depends(require_admin)) -> ModelVersionSummary:
    svc = get_services()
    try:
        payload = svc.model_observation.promote_model(model_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ModelVersionSummary(**payload)
