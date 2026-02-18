from __future__ import annotations

from fastapi import APIRouter, Query

from app.core.services import get_services
from app.domain.models import CardView

router = APIRouter(prefix="/api/cards", tags=["cards"])


@router.get("", response_model=list[CardView])
def list_cards(
    query: str = Query(default="", max_length=120),
    limit: int = Query(default=600, ge=1, le=1200),
) -> list[CardView]:
    svc = get_services()
    rows = svc.cards.search(query, limit=limit)
    out: list[CardView] = []
    for card in rows:
        out.append(
            CardView(
                title=card.title,
                cardType=card.card_type,
                superType=card.super_type,
                domains=list(card.domains),
                championTags=list(card.champion_tags),
                cost=card.cost,
                might=card.might,
                isUnique=bool(card.is_unique),
                imageUrl=card.image_url,
                rarity=card.rarity,
                set=card.set_name,
                cardNumber=card.card_number,
                effect=card.effect,
                flavor=card.flavor,
                tags=list(card.tags),
                promo=bool(card.promo),
            )
        )
    return out
