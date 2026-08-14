"""
用户管理（企微绑定）

- GET    /api/admin/users                  用户列表（可筛选）
- PUT    /api/admin/users/{id}/wechat      绑定企微 userid
- DELETE /api/admin/users/{id}/wechat      解绑

权限：user:manage（SUPER_ADMIN / TENANT_ADMIN）
范围：SUPER_ADMIN 全量；租户管理员仅本租户
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from work_agent.api.deps import get_db, require_permission
from work_agent.api.schemas import (
    CreateUserRequest,
    UpdateUserRequest,
    UserAdminOut,
    UserAdminPage,
    WechatBindRequest,
)
from work_agent.db.models import User
from work_agent.repositories.task_repository import TaskRepository
from work_agent.repositories.user_repository import UserRepository
from work_agent.services.audit_service import AuditService
from work_agent.services.auth_service import AuthService
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


# RBAC 角色码 → User.role 显示名
ROLE_DISPLAY = {
    "SUPER_ADMIN": "超级管理员",
    "TENANT_ADMIN": "租户管理员",
    "DEPARTMENT_ADMIN": "部门管理员",
    "USER": "员工",
}

# 租户管理员可授予的角色（不能提权到租户/平台管理员）
_TENANT_ADMIN_GRANTABLE = {
    "USER",
    "DEPARTMENT_ADMIN",
}


def _validate_role_grant(
        db: Session,
        operator: User,
        role_code: str
) -> None:

    """
    角色授予校验：SUPER_ADMIN 可赋任意；租户管理员仅 USER/DEPARTMENT_ADMIN
    """

    if role_code not in ROLE_DISPLAY:

        raise HTTPException(
            status_code=400,
            detail=f"未知角色: {role_code}",
        )

    if (
        not _is_super_admin(db, operator)
        and role_code not in _TENANT_ADMIN_GRANTABLE
    ):

        raise HTTPException(
            status_code=403,
            detail=f"无权授予角色 {role_code}",
        )


def _client_ip(
        request: Request
) -> str | None:

    client = getattr(
        request,
        "client",
        None,
    )

    return (
        client.host
        if client
        else None
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
        real_name=user.real_name,
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


@router.post(
    "/users",
    response_model=UserAdminOut,
    status_code=201
)
def create_user(
        payload: CreateUserRequest,
        request: Request,
        current_user: User = Depends(
            require_permission("user:manage")
        ),
        db: Session = Depends(get_db),
):

    """
    新建用户（Web）

    - SUPER_ADMIN 可建任意租户/任意角色；租户管理员仅本租户 + USER/DEPARTMENT_ADMIN
    - username 唯一；wechat_user_id 冲突 409；密码 ≥6 位
    """

    repo = UserRepository()

    username = payload.username.strip()

    if not username:

        raise HTTPException(
            status_code=400,
            detail="用户名不能为空",
        )

    if repo.get_by_username(
            db,
            username,
    ):

        raise HTTPException(
            status_code=409,
            detail=f"用户名已存在: {username}",
        )

    if not payload.password or len(payload.password) < 6:

        raise HTTPException(
            status_code=400,
            detail="密码至少 6 位",
        )

    role_code = (
        payload.role.strip()
        or "USER"
    )

    _validate_role_grant(
        db,
        current_user,
        role_code,
    )

    # 租户：SUPER_ADMIN 可设任意/空；租户管理员强制本租户
    if _is_super_admin(
            db,
            current_user,
    ):

        tenant_id = payload.tenant_id.strip()

    else:

        if (
            payload.tenant_id.strip()
            and payload.tenant_id.strip() != current_user.tenant_id
        ):

            raise HTTPException(
                status_code=403,
                detail="租户管理员只能在本租户创建用户",
            )

        tenant_id = current_user.tenant_id

    # 企微绑定冲突
    wechat_user_id = (
        payload.wechat_user_id.strip()
        or None
    )

    if wechat_user_id:

        existing = repo.get_by_wechat_user_id(
            db,
            wechat_user_id,
        )

        if existing:

            raise HTTPException(
                status_code=409,
                detail=(
                    f"该企微账号已绑定用户 "
                    f"「{existing.username}」"
                ),
            )

    user = repo.create(
        db,
        username=username,
        password_hash=AuthService.hash_password(
            payload.password
        ),
        department=payload.department.strip(),
        role=ROLE_DISPLAY[role_code],
        real_name=(
            payload.real_name.strip()
            or username
        ),
        wechat_user_id=wechat_user_id,
        tenant_id=tenant_id,
    )

    RBACService().assign_role(
        db,
        user.id,
        role_code,
    )

    AuditService().log_operation(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="user.create",
        target_type="user",
        target_id=str(user.id),
        ip=_client_ip(request),
        user_agent=request.headers.get(
            "user-agent"
        ),
    )

    db.refresh(user)

    return _user_out(
        db,
        user,
    )


@router.put(
    "/users/{user_id}",
    response_model=UserAdminOut
)
def update_user(
        user_id: int,
        payload: UpdateUserRequest,
        request: Request,
        current_user: User = Depends(
            require_permission("user:manage")
        ),
        db: Session = Depends(get_db),
):

    """
    编辑用户资料（real_name/部门/角色/租户）

    - 跨租户 403；改租户时有任务的用户拒绝 409
    - 角色授予沿用 _validate_role_grant
    """

    repo = UserRepository()

    target = repo.get_by_id(
        db,
        user_id,
    )

    if not target:

        raise HTTPException(
            status_code=404,
            detail="用户不存在",
        )

    if not _can_manage(
            db,
            current_user,
            target,
    ):

        raise HTTPException(
            status_code=403,
            detail="无权管理该用户",
        )

    if payload.real_name is not None:

        target.real_name = (
            payload.real_name.strip()
            or target.username
        )

    if payload.department is not None:

        target.department = payload.department.strip()

    if payload.role:

        role_code = payload.role.strip()

        _validate_role_grant(
            db,
            current_user,
            role_code,
        )

        target.role = ROLE_DISPLAY[role_code]

        RBACService().assign_role(
            db,
            target.id,
            role_code,
        )

    if payload.tenant_id is not None:

        new_tenant = payload.tenant_id.strip()

        if not _is_super_admin(
                db,
                current_user,
        ) and new_tenant != current_user.tenant_id:

            raise HTTPException(
                status_code=403,
                detail="租户管理员只能操作本租户",
            )

        if new_tenant != target.tenant_id:

            if (
                TaskRepository().count_by_employee(
                    db,
                    target.id,
                )
                > 0
            ):

                raise HTTPException(
                    status_code=409,
                    detail="该用户已有任务，不能变更租户",
                )

            target.tenant_id = new_tenant

    db.commit()

    AuditService().log_operation(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="user.update",
        target_type="user",
        target_id=str(target.id),
        ip=_client_ip(request),
        user_agent=request.headers.get(
            "user-agent"
        ),
    )

    db.refresh(target)

    return _user_out(
        db,
        target,
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

        try:

            db.commit()

        except IntegrityError:

            # 并发竞态：唯一索引兜底，回滚返回 409
            db.rollback()

            raise HTTPException(
                status_code=409,
                detail="该企微账号已被绑定（并发冲突）",
            )

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
