from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, Response

from app.auth.dependencies import require_user
from app.core.rate_limits import limiter
from app.core.services import get_services
from app.domain.models import CardView
from app.api.routers.decks import card_to_view

router = APIRouter(prefix="/api/cards", tags=["cards"])


@router.get("", response_model=list[CardView])
@limiter.limit("60/minute")
def list_cards(
    request: Request,
    response: Response,
    query: str = Query(default="", max_length=120),
    limit: int = Query(default=600, ge=1, le=1200),
    _auth=Depends(require_user),
) -> list[CardView]:
    svc = get_services()
    rows = svc.cards.search(query, limit=limit)
    response.headers["Cache-Control"] = "private, max-age=300"
    return [card_to_view(card) for card in rows]
