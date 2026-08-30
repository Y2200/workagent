from sqlalchemy.orm import Session

from work_agent.db.models import User, UserRole, Role


class UserRepository:

    """
    用户数据访问
    """

    def get_by_username(
            self,
            db: Session,
            username: str
    ):

        return (
            db.query(User)
            .filter(User.username == username)
            .first()
        )


    def get_by_id(
            self,
            db: Session,
            user_id: int
    ):

        return db.get(
            User,
            user_id
        )


    def get_by_wechat_user_id(
            self,
            db: Session,
            wechat_user_id: str
    ):

        return (
            db.query(User)
            .filter(User.wechat_user_id == wechat_user_id)
            .first()
        )


    def list_by_tenant(
            self,
            db: Session,
            tenant_id: str
    ):

        """
        按租户查询用户
        """

        return (
            db.query(User)
            .filter(User.tenant_id == tenant_id)
            .order_by(User.id)
            .all()
        )


    def list_all(
            self,
            db: Session,
            tenant_id: str = "",
            keyword: str = ""
    ):

        """
        用户管理列表（企微绑定用）

        tenant_id 非空时按租户过滤（租户管理员）；空则平台全量（SUPER_ADMIN）
        """

        query = db.query(User)

        if tenant_id:

            query = query.filter(
                User.tenant_id == tenant_id
            )

        if keyword:

            like = f"%{keyword}%"

            query = query.filter(
                (
                    User.username.like(like)
                    | User.department.like(like)
                    | User.wechat_user_id.like(like)
                )
            )

        return (
            query.order_by(User.id)
            .all()
        )


    def search_by_name(
            self,
            db: Session,
            keyword: str,
            tenant_id: str = ""
    ) -> list[User]:

        """
        按姓名/账号精确或模糊解析员工（Enterprise Agent user_tool）

        tenant_id 非空时限定本租户（租户管理员/部门管理员）；
        空则平台全量（SUPER_ADMIN）。
        优先 real_name/username 精确匹配，其次模糊（like）。
        """

        if not keyword:
            return []

        query = db.query(User)

        if tenant_id:
            query = query.filter(
                User.tenant_id == tenant_id
            )

        like = f"%{keyword}%"

        return (
            query.filter(
                (
                    User.real_name.like(like)
                    | User.username.like(like)
                    | User.wechat_user_id.like(like)
                )
            )
            .order_by(
                # 精确匹配优先
                (User.real_name == keyword).desc(),
                (User.username == keyword).desc(),
                User.id,
            )
            .limit(20)
            .all()
        )


    def list_by_department(
            self,
            db: Session,
            department: str,
            tenant_id: str = ""
    ) -> list[User]:

        """
        按部门查询用户（Enterprise Agent 部门成员）

        多租户铁律：tenant_id 非空时按租户过滤
        """

        if not department:
            return []

        query = db.query(User)

        if tenant_id:
            query = query.filter(
                User.tenant_id == tenant_id
            )

        return (
            query.filter(
                User.department == department
            )
            .order_by(User.id)
            .all()
        )


    def create(
            self,
            db: Session,
            username: str,
            password_hash: str,
            department: str = "",
            role: str = "员工",
            real_name: str = "",
            email: str = "",
            wechat_user_id: str | None = None,
            tenant_id: str = ""
    ) -> User:

        user = User(
            tenant_id=tenant_id,
            username=username,
            password_hash=password_hash,
            department=department,
            role=role,
            real_name=real_name,
            email=email,
            wechat_user_id=wechat_user_id
        )

        db.add(user)

        db.commit()

        db.refresh(user)

        return user

    def delete(
            self,
            db: Session,
            user: User
    ) -> None:

        """
        删除用户（调用方需先清理 user_role/会话等关联）
        """

        db.delete(user)

        db.commit()

    def count_super_admins(
            self,
            db: Session,
            exclude_id: int | None = None
    ) -> int:

        """
        统计超级管理员数量（删除保护：不能删最后一个 SUPER_ADMIN）
        """

        query = (
            db.query(User)
            .join(UserRole, UserRole.user_id == User.id)
            .join(Role, Role.id == UserRole.role_id)
            .filter(Role.code == "SUPER_ADMIN")
        )

        if exclude_id is not None:

            query = query.filter(
                User.id != exclude_id
            )

        return query.count()
