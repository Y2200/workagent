from sqlalchemy.orm import Session

from work_agent.repositories.rbac_repository import RBACRepository


class RBACService:

    """
    RBAC 权限服务（领域层）

    只依赖 RBACRepository，不做直接数据访问
    """

    def __init__(
            self,
            repository: RBACRepository | None = None
    ):

        self.repository = repository or RBACRepository()


    def get_permission_codes(
            self,
            db: Session,
            user_id: int
    ) -> set[str]:

        """
        解析用户全部权限码
        """

        return self.repository.get_permission_codes(
            db,
            user_id
        )


    def has_permission(
            self,
            db: Session,
            user_id: int,
            code: str
    ) -> bool:

        return code in self.get_permission_codes(
            db,
            user_id
        )


    def get_role_codes(
            self,
            db: Session,
            user_id: int
    ) -> set[str]:

        """
        解析用户全部角色码
        """

        return self.repository.get_role_codes(
            db,
            user_id
        )


    # ======================
    # 角色/权限管理（供 seed 使用）
    # ======================

    def get_role_by_code(
            self,
            db: Session,
            code: str
    ):

        return self.repository.get_role_by_code(
            db,
            code
        )


    def get_permission_by_code(
            self,
            db: Session,
            code: str
    ):

        return self.repository.get_permission_by_code(
            db,
            code
        )


    def create_role(
            self,
            db: Session,
            *,
            code: str,
            name: str,
            description: str = "",
            tenant_id: str = ""
    ):

        role = self.get_role_by_code(
            db,
            code
        )

        if role:
            return role

        return self.repository.create_role(
            db,
            code=code,
            name=name,
            description=description,
            tenant_id=tenant_id,
        )


    def create_permission(
            self,
            db: Session,
            *,
            code: str,
            name: str,
            description: str = ""
    ):

        permission = self.get_permission_by_code(
            db,
            code
        )

        if permission:
            return permission

        return self.repository.create_permission(
            db,
            code=code,
            name=name,
            description=description,
        )


    def assign_permission(
            self,
            db: Session,
            role_id: int,
            permission_id: int
    ) -> None:

        self.repository.assign_permission(
            db,
            role_id,
            permission_id,
        )


    def assign_role(
            self,
            db: Session,
            user_id: int,
            role_code: str
    ):

        role = self.get_role_by_code(
            db,
            role_code
        )

        if not role:
            return None

        self.repository.assign_role(
            db,
            user_id,
            role.id,
        )

        return role
