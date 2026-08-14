"""
任务管理 API（Web 端）

- GET  /api/admin/tasks            任务列表（租户隔离，可按状态过滤）
- POST /api/admin/tasks            创建任务
- GET  /api/admin/tasks/{id}       任务详情（含提交记录）
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from work_agent.api.deps import get_db, require_permission
from work_agent.api.schemas import (
    TaskCreateRequest,
    TaskDetailOut,
    TaskOut,
    TaskUpdateOut,
)
from work_agent.core.container import (
    notification_service,
    task_report_service,
    task_stats_service,
    task_service,
)
from work_agent.db.models import User
from work_agent.repositories.user_repository import UserRepository
from work_agent.services.audit_service import AuditService
from work_agent.services.rbac_service import RBACService


router = APIRouter(
    prefix="/api/admin",
    tags=["admin"],
)


def _client_ip(request: Request) -> str | None:

    if request.client:

        return request.client.host

    return None


def _tenant_scope(
        db: Session,
        current_user: User
) -> str | None:

    """
    平台管理员（SUPER_ADMIN）→ None（查看全部租户任务）
    普通租户管理员 → 本租户隔离
    """

    if (
        "SUPER_ADMIN"
        in RBACService().get_role_codes(
            db,
            current_user.id,
        )
    ):

        return None

    return current_user.tenant_id


def _enrich(
        db: Session,
        tasks
) -> list[dict]:

    """
    富化负责人用户名（避免前端依赖 user:manage 权限）
    """

    user_ids = {
        t.employee_id
        for t in tasks
    }

    users = {
        u.id: u.username
        for u in (
            db.query(User)
            .filter(User.id.in_(user_ids))
            .all()
        )
    }

    return [
        {
            **TaskOut.model_validate(t).model_dump(),
            "employee_username": users.get(
                t.employee_id,
                "",
            ),
        }
        for t in tasks
    ]


@router.get(
    "/task/employees",
    response_model=list[dict]
)
def task_employees(
        current_user: User = Depends(
            require_permission("task:create")
        ),
        db: Session = Depends(get_db),
):

    """
    可指派负责人列表（租户内用户；SUPER_ADMIN 全量）
    """

    is_super = (
        "SUPER_ADMIN"
        in RBACService().get_role_codes(
            db,
            current_user.id,
        )
    )

    tenant_scope = (
        ""
        if is_super
        else current_user.tenant_id
    )

    users = UserRepository().list_all(
        db,
        tenant_id=tenant_scope,
    )

    return [
        {
            "id": u.id,
            "username": u.username,
            "department": u.department,
            "tenant_id": u.tenant_id,
        }
        for u in users
    ]


@router.get(
    "/tasks",
    response_model=list[TaskOut]
)
def list_tasks(
        status: str | None = Query(None),
        current_user: User = Depends(
            require_permission("task:view")
        ),
        db: Session = Depends(get_db),
):

    """
    任务列表（SUPER_ADMIN 全量；租户管理员本租户）
    """

    tasks = task_service.list_tasks_for_web(
        tenant_id=_tenant_scope(db, current_user),
        status=status,
    )

    return _enrich(
        db,
        tasks,
    )


@router.post(
    "/tasks",
    response_model=TaskOut,
    status_code=201
)
def create_task(
        payload: TaskCreateRequest,
        request: Request,
        current_user: User = Depends(
            require_permission("task:create")
        ),
        db: Session = Depends(get_db),
):

    """
    创建任务（指定负责人/截止/优先级）
    """

    if not payload.title.strip():

        raise HTTPException(
            status_code=400,
            detail="任务名称不能为空"
        )

    if payload.priority not in ("low", "normal", "high"):

        raise HTTPException(
            status_code=400,
            detail="priority 仅支持 low/normal/high"
        )

    try:

        task = task_service.create_task(
            creator_tenant_id=current_user.tenant_id,
            title=payload.title.strip(),
            description=payload.description,
            creator_id=current_user.id,
            manager_id=payload.manager_id,
            employee_id=payload.employee_id,
            department=payload.department,
            deadline=payload.deadline,
            priority=payload.priority,
        )

    except ValueError as exc:

        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )

    AuditService().log_operation(
        # 记录任务所属租户，而非创建者租户（创建者可能是平台管理员）
        tenant_id=task.tenant_id,
        user_id=current_user.id,
        action="task.create",
        target_type="task",
        target_id=str(task.id),
        ip=_client_ip(request),
        user_agent=request.headers.get(
            "user-agent"
        ),
    )

    # 发布任务企微提醒（失败不影响任务创建——内部吞异常 + 落库 failed）
    notification_service.send_task_created(task)

    return _enrich(
        db,
        [task],
    )[0]


@router.get(
    "/tasks/{task_id}",
    response_model=TaskDetailOut
)
def get_task(
        task_id: int,
        current_user: User = Depends(
            require_permission("task:view")
        ),
        db: Session = Depends(get_db),
):

    """
    任务详情（含提交记录）
    """

    task = task_service.get_task(
        tenant_id=_tenant_scope(db, current_user),
        task_id=task_id,
    )

    if not task:

        raise HTTPException(
            status_code=404,
            detail="任务不存在"
        )

    updates = task_service.list_task_updates(
        tenant_id=current_user.tenant_id,
        task_id=task_id,
    )

    enriched = _enrich(
        db,
        [task],
    )[0]

    return TaskDetailOut(
        **enriched,
        updates=[
            TaskUpdateOut.model_validate(u)
            for u in updates
        ],
    )


# ======================
# Phase 4：任务统计 / 导出 / 周报
# ======================

_EXPORT_TYPES = {
    "xlsx": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "task_stats.xlsx",
    ),
    "docx": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "task_stats.docx",
    ),
}


@router.get(
    "/task/stats"
)
def task_stats(
        current_user: User = Depends(
            require_permission("task:manage")
        ),
        db: Session = Depends(get_db),
):

    """
    任务统计（总览/按部门/按员工/风险任务；SUPER_ADMIN 全量，租户管理员本租户）
    """

    return task_stats_service.get_stats(
        tenant_id=_tenant_scope(db, current_user),
    )


@router.get(
    "/task/stats/export"
)
def task_stats_export(
        format: str = Query(
            "xlsx",
            pattern="^(xlsx|docx)$",
        ),
        current_user: User = Depends(
            require_permission("task:manage")
        ),
        db: Session = Depends(get_db),
):

    """
    导出任务统计（Excel/Word）
    """

    stats = task_stats_service.get_stats(
        tenant_id=_tenant_scope(db, current_user),
    )

    if format == "xlsx":

        data = task_stats_service.to_xlsx(stats)

    else:

        data = task_stats_service.to_docx(stats)

    content_type, filename = _EXPORT_TYPES[format]

    return StreamingResponse(
        iter([data]),
        media_type=content_type,
        headers={
            "Content-Disposition": (
                f'attachment; filename="{filename}"'
            )
        },
    )


@router.get(
    "/task/report/weekly"
)
def weekly_report(
        current_user: User = Depends(
            require_permission("task:manage")
        ),
        db: Session = Depends(get_db),
):

    """
    本周任务周报（JSON 摘要）
    """

    return task_report_service.build_weekly_report(
        tenant_id=_tenant_scope(db, current_user),
    )


@router.get(
    "/task/report/weekly/export"
)
def weekly_report_export(
        format: str = Query(
            "docx",
            pattern="^docx$",
        ),
        current_user: User = Depends(
            require_permission("task:manage")
        ),
        db: Session = Depends(get_db),
):

    """
    下载本周任务周报（Word）
    """

    data = task_report_service.generate_weekly(
        tenant_id=_tenant_scope(db, current_user),
    )["docx_bytes"]

    return StreamingResponse(
        iter([data]),
        media_type=(
            "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document"
        ),
        headers={
            "Content-Disposition": (
                'attachment; filename="weekly_report.docx"'
            )
        },
    )
