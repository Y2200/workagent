from fastapi import APIRouter, Depends

from work_agent.api.deps import get_current_user, require_permission
from work_agent.core.resilience import list_breaker_statuses
from work_agent.db.models import User


router = APIRouter(
    prefix="/api/admin/resilience",
    tags=["resilience"]
)


@router.get(
    "/status",
    response_model=dict
)
def resilience_status(
        current_user: User = Depends(require_permission("system:manage"))
):

    """
    故障恢复状态（熔断器状态 + 重试统计）
    """

    return {
        "breakers": list_breaker_statuses(),
    }
