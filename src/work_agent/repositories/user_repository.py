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


    def create(
            self,
            db: Session,
            username: str,
            password_hash: str,
            department: str = "",
            role: str = "员工",
            wechat_user_id: str | None = None,
            tenant_id: str = ""
    ) -> User:

        user = User(
            tenant_id=tenant_id,
            username=username,
            password_hash=password_hash,
            department=department,
            role=role,
            wechat_user_id=wechat_user_id
        )

        db.add(user)

        db.commit()

        db.refresh(user)

        return user
