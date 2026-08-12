from fastapi import APIRouter, Depends

from work_agent.api.deps import get_current_user, require_permission
from work_agent.api.schemas import BudgetUpdateRequest
from work_agent.core.container import cost_governance_service
from work_agent.db.models import User


router = APIRouter(
    prefix="/api/admin/cost",
    tags=["cost"]
)


@router.get(
    "/usage",
    response_model=dict
)
def cost_usage(
        current_user: User = Depends(require_permission("audit:view"))
):

    """
    LLM 成本用量分析（按租户隔离）
    """

    return cost_governance_service.usage(
        tenant_id=current_user.tenant_id
    )


@router.get(
    "/budget",
    response_model=dict
)
def get_budget(
        current_user: User = Depends(require_permission("system:manage"))
):

    """
    当前租户月度预算
    """

    return {
        "budget": cost_governance_service.get_budget(
            current_user.tenant_id
        ),
        "quota": cost_governance_service.check_quota(
            current_user.tenant_id
        ),
    }


@router.put(
    "/budget",
    response_model=dict
)
def update_budget(
        payload: BudgetUpdateRequest,
        current_user: User = Depends(require_permission("system:manage"))
):

    """
    设置月度预算（null = 不限制）
    """

    if payload.budget is not None and payload.budget < 0:

        from fastapi import HTTPException

        raise HTTPException(
            status_code=400,
            detail="预算不能为负数"
        )

    cost_governance_service.set_budget(
        tenant_id=current_user.tenant_id,
        budget=payload.budget,
        updated_by=current_user.username,
    )

    return {
        "budget": cost_governance_service.get_budget(
            current_user.tenant_id
        ),
    }
