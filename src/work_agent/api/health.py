from fastapi import APIRouter, Depends

from work_agent.api.deps import get_current_user, require_permission
from work_agent.core.health_metrics import health_metrics
from work_agent.core.resilience import list_breaker_statuses
from work_agent.core.container import health_service
from work_agent.db.models import User


router = APIRouter(
    tags=["health"]
)


@router.get(
    "/health/ready"
)
def health_ready():
    """
    就绪探针（关键依赖 PG/Milvus/MinIO 全部 ok）
    """

    return health_service.readiness()


@router.get(
    "/api/admin/health/components"
)
def health_components(
        current_user: User = Depends(require_permission("system:manage"))
):

    """
    组件健康检查（各依赖探活）
    """

    return {
        "components": health_service.check_components(),
    }


@router.get(
    "/api/admin/health/metrics"
)
def health_metrics_view(
        current_user: User = Depends(require_permission("system:manage"))
):

    """
    运行时指标（请求/错误/延迟/token）
    """

    return health_metrics.snapshot()


@router.get(
    "/api/admin/health/resilience"
)
def health_resilience(
        current_user: User = Depends(require_permission("system:manage"))
):

    """
    故障恢复状态（熔断器）
    """

    return {
        "breakers": list_breaker_statuses(),
    }
