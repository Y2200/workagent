from sqlalchemy.orm import Session

from work_agent.db.models import Permission, Role, RolePermission, UserRole


class RBACRepository:

    """
    RBAC 数据访问

    封装角色/权限/用户角色的数据操作
    """

    def get_permission_codes(
            self,
            db: Session,
            user_id: int
    ) -> set[str]:

        """
        解析用户全部权限码
        """

        rows = (
            db.query(Permission.code)
            .join(
                RolePermission,
                RolePermission.permission_id == Permission.id,
            )
            .join(
                UserRole,
                UserRole.role_id == RolePermission.role_id,
            )
            .filter(UserRole.user_id == user_id)
            .all()
        )

        return {
            code
            for (code,) in rows
        }


    def get_role_codes(
            self,
            db: Session,
            user_id: int
    ) -> set[str]:

        """
        解析用户全部角色码
        """

        rows = (
            db.query(Role.code)
            .join(
                UserRole,
                UserRole.role_id == Role.id,
            )
            .filter(UserRole.user_id == user_id)
            .all()
        )

        return {
            code
            for (code,) in rows
        }


    def list_user_ids_by_role(
            self,
            db: Session,
            role_code: str
    ) -> list[int]:

        """
        按角色码查询所有用户 id（Enterprise Agent 部门管理员 digest 用）
        """

        rows = (
            db.query(UserRole.user_id)
            .join(
                Role,
                Role.id == UserRole.role_id,
            )
            .filter(Role.code == role_code)
            .all()
        )

        return [
            user_id
            for (user_id,) in rows
        ]


    def get_role_by_code(
            self,
            db: Session,
            code: str
    ):

        return (
            db.query(Role)
            .filter(Role.code == code)
            .first()
        )


    def get_permission_by_code(
            self,
            db: Session,
            code: str
    ):

        return (
            db.query(Permission)
            .filter(Permission.code == code)
            .first()
        )


    def create_role(
            self,
            db: Session,
            *,
            code: str,
            name: str,
            description: str = "",
            tenant_id: str = ""
    ) -> Role:

        role = Role(
            code=code,
            name=name,
            description=description,
            tenant_id=tenant_id,
        )

        db.add(role)

        db.commit()

        db.refresh(role)

        return role


    def create_permission(
            self,
            db: Session,
            *,
            code: str,
            name: str,
            description: str = ""
    ) -> Permission:

        permission = Permission(
            code=code,
            name=name,
            description=description,
        )

        db.add(permission)

        db.commit()

        db.refresh(permission)

        return permission


    def assign_permission(
            self,
            db: Session,
            role_id: int,
            permission_id: int
    ) -> None:

        exists = (
            db.query(RolePermission)
            .filter(
                RolePermission.role_id == role_id,
                RolePermission.permission_id == permission_id,
            )
            .first()
        )

        if exists:
            return

        db.add(
            RolePermission(
                role_id=role_id,
                permission_id=permission_id,
            )
        )

        db.commit()


    def assign_role(
            self,
            db: Session,
            user_id: int,
            role_id: int
    ) -> None:

        exists = (
            db.query(UserRole)
            .filter(
                UserRole.user_id == user_id,
                UserRole.role_id == role_id,
            )
            .first()
        )

        if exists:
            return

        db.add(
            UserRole(
                user_id=user_id,
                role_id=role_id,
            )
        )

        db.commit()
