from sqlalchemy.orm import Session

from work_agent.db.models import User


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


    def create(
            self,
            db: Session,
            username: str,
            password_hash: str,
            department: str = "",
            role: str = "员工",
            real_name: str = "",
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
            wechat_user_id=wechat_user_id
        )

        db.add(user)

        db.commit()

        db.refresh(user)

        return user
