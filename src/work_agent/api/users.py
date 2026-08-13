"""
用户管理（企微绑定）

- GET    /api/admin/users                  用户列表（可筛选）
- PUT    /api/admin/users/{id}/wechat      绑定企微 userid
- DELETE /api/admin/users/{id}/wechat      解绑

权限：user:manage（SUPER_ADMIN / TENANT_ADMIN）
范围：SUPER_ADMIN 全量；租户管理员仅本租户
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from work_agent.api.deps import get_db, require_permission
from work_agent.api.schemas import (
    UserAdminOut,
    UserAdminPage,
    WechatBindRequest,
)
from work_agent.db.models import User
from work_agent.repositories.user_repository import UserRepository
from work_agent.services.audit_service import AuditService
from work_agent.services.rbac_service import RBACService


router = APIRouter(
    prefix="/api/admin",
    tags=["admin"],
)


def _is_super_admin(
        db: Session,
        user: User
) -> bool:

    return (
        "SUPER_ADMIN"
        in RBACService().get_role_codes(
            db,
            user.id,
        )
    )


def _can_manage(
        db: Session,
        operator: User,
        target: User
) -> bool:
    """
    SUPER_ADMIN 可管理任意用户；租户管理员仅本租户
    """

    if _is_super_admin(
            db,
            operator,
    ):

        return True

    return (
        target.tenant_id
        == operator.tenant_id
    )


def _user_out(
        db: Session,
        user: User
) -> UserAdminOut:

    roles = sorted(
        RBACService().get_role_codes(
            db,
            user.id,
        )
    )

    return UserAdminOut(
        id=user.id,
        username=user.username,
        department=user.department,
        role=user.role,
        tenant_id=user.tenant_id,
        wechat_user_id=user.wechat_user_id,
        roles=roles,
        created_at=user.created_at,
    )


@router.get(
    "/users",
    response_model=UserAdminPage
)
def list_users(
        keyword: str = Query(
            "",
            max_length=64,
        ),
        current_user: User = Depends(
            require_permission("user:manage")
        ),
        db: Session = Depends(get_db),
):

    """
    用户列表（平台管理员全量；租户管理员本租户）
    """

    tenant_scope = (
        ""
        if _is_super_admin(db, current_user)
        else current_user.tenant_id
    )

    users = UserRepository().list_all(
        db,
        tenant_id=tenant_scope,
        keyword=keyword.strip(),
    )

    return UserAdminPage(
        items=[
            _user_out(db, u)
            for u in users
        ],
        total=len(users),
    )


@router.put(
    "/users/{user_id}/wechat",
    response_model=UserAdminOut
)
def bind_wechat(
        user_id: int,
        payload: WechatBindRequest,
        request: Request,
        current_user: User = Depends(
            require_permission("user:manage")
        ),
        db: Session = Depends(get_db),
):

    """
    绑定企微 userid（空串 = 解绑）
    """

    repo = UserRepository()

    target = repo.get_by_id(
        db,
        user_id,
    )

    if not target:

        raise HTTPException(
            status_code=404,
            detail="用户不存在"
        )

    if not _can_manage(
            db,
            current_user,
            target,
    ):

        raise HTTPException(
            status_code=403,
            detail="无权管理该用户"
        )

    wechat_user_id = payload.wechat_user_id.strip()

    # 解绑
    if not wechat_user_id:

        target.wechat_user_id = None

        db.commit()

        action = "user.wechat_unbind"

    else:

        # 冲突检测：该企微账号已被他人绑定
        existing = repo.get_by_wechat_user_id(
            db,
            wechat_user_id,
        )

        if existing and existing.id != target.id:

            raise HTTPException(
                status_code=409,
                detail=(
                    f"该企微账号已绑定用户 "
                    f"「{existing.username}」"
                )
            )

        target.wechat_user_id = wechat_user_id

        db.commit()

        action = "user.wechat_bind"

    AuditService().log_operation(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action=action,
        target_type="user",
        target_id=str(target.id),
        ip=getattr(request, "client", None).host
        if getattr(request, "client", None)
        else None,
        user_agent=request.headers.get(
            "user-agent"
        ),
    )

    db.refresh(target)

    return _user_out(
        db,
        target,
    )


@router.delete(
    "/users/{user_id}/wechat",
    response_model=UserAdminOut
)
def unbind_wechat(
        user_id: int,
        current_user: User = Depends(
            require_permission("user:manage")
        ),
        db: Session = Depends(get_db),
):

    """
    解绑企微 userid
    """

    repo = UserRepository()

    target = repo.get_by_id(
        db,
        user_id,
    )

    if not target:

        raise HTTPException(
            status_code=404,
            detail="用户不存在"
        )

    if not _can_manage(
            db,
            current_user,
            target,
    ):

        raise HTTPException(
            status_code=403,
            detail="无权管理该用户"
        )

    target.wechat_user_id = None

    db.commit()

    AuditService().log_operation(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="user.wechat_unbind",
        target_type="user",
        target_id=str(target.id),
    )

    db.refresh(target)

    return _user_out(
        db,
        target,
    )
