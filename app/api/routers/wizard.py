from fastapi import APIRouter, Depends, Request

from app.auth.dependencies import AuthContext, require_user
from app.core.rate_limits import limiter
from app.core.services import get_services
from app.domain.models import WizardSolveRequest
from app.domain.wizard_solver import solve_wizard_deck

router = APIRouter(prefix="/api/wizard", tags=["wizard"])


@router.post("/solve")
@limiter.limit("20/minute")
def wizard_solve(
    request: Request,
    body: WizardSolveRequest,
    auth: AuthContext = Depends(require_user),
) -> dict:
    svc = get_services()
    owned = body.owned if body.owned else svc.storage.get_effective_collection(user_id=auth.user_id)
    rules = svc.rules_for_format(body.format)
    result = solve_wizard_deck(
        legend_title=body.legend_title,
        chosen_champion_title=body.chosen_champion_title,
        format_name=body.format,
        owned=owned,
        rules=rules,
        cards=svc.cards,
        reference_deck=body.reference_deck,
        current_deck=body.current_deck,
        swaps=[swap.model_dump() for swap in body.swaps],
    )
    return {
        "deck": result.deck.model_dump(by_alias=True),
        "validation": result.validation.model_dump(),
        "metrics": result.metrics,
        "diff": result.diff,
        "explanations": result.explanations,
        "playlist": result.playlist,
        "replacementClusters": result.replacement_clusters,
        "solverStatus": result.solver_status,
    }
