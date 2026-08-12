from fastapi import APIRouter, Depends, HTTPException, Query

from work_agent.api.deps import get_current_user, require_permission
from work_agent.api.schemas import TraceDetailOut, TracePage
from work_agent.core.container import trace_service
from work_agent.db.models import User


router = APIRouter(
    prefix="/api/admin/traces",
    tags=["trace"]
)


@router.get(
    "",
    response_model=TracePage
)
def list_traces(
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=100),
        status: str | None = Query(None),
        channel: str | None = Query(None),
        current_user: User = Depends(require_permission("audit:view"))
):

    """
    链路追踪列表（按租户隔离）
    """

    return trace_service.list_traces(
        tenant_id=current_user.tenant_id,
        status=status,
        channel=channel,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/{request_id}",
    response_model=TraceDetailOut
)
def get_trace(
        request_id: str,
        current_user: User = Depends(require_permission("audit:view"))
):

    """
    追踪详情（含 spans 瀑布，租户隔离）
    """

    result = trace_service.get_trace(
        request_id=request_id,
        tenant_id=current_user.tenant_id,
    )

    if not result:

        raise HTTPException(
            status_code=404,
            detail="追踪不存在或无权查看",
        )

    return result
