from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from work_agent.db.models import User
from work_agent.db.session import get_db
from work_agent.repositories.user_repository import UserRepository
from work_agent.services.auth_service import AuthService
from work_agent.services.rbac_service import RBACService


_bearer = HTTPBearer(
    auto_error=False
)


def get_current_user(
        credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
        db: Session = Depends(get_db)
) -> User:

    """
    解析 Bearer JWT，返回当前用户
    """

    if not credentials:

        raise HTTPException(
            status_code=401,
            detail="未提供认证令牌"
        )

    user_id = AuthService.decode_token(
        credentials.credentials
    )

    if user_id is None:

        raise HTTPException(
            status_code=401,
            detail="令牌无效或已过期"
        )

    user = UserRepository().get_by_id(
        db,
        user_id
    )

    if not user:

        raise HTTPException(
            status_code=401,
            detail="用户不存在"
        )

    return user


def get_current_admin(
        user: User = Depends(get_current_user)
) -> User:

    """
    要求当前用户是管理员（兼容旧角色字段）

    新代码请优先使用 require_permission
    """

    if user.role != "管理员":

        raise HTTPException(
            status_code=403,
            detail="需要管理员权限"
        )

    return user


def require_permission(
        code: str
):

    """
    返回一个依赖，要求当前用户拥有指定权限码

    用法：
        current_user: User = Depends(require_permission("document:delete"))
    """

    def checker(
            user: User = Depends(get_current_user),
            db: Session = Depends(get_db)
    ) -> User:

        rbac_service = RBACService()

        if not rbac_service.has_permission(
                db,
                user.id,
                code
        ):

            raise HTTPException(
                status_code=403,
                detail=f"权限不足: 需要 {code}"
            )

        return user

    return checker
