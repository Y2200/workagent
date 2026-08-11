from sqlalchemy import BigInteger, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from work_agent.db.base import Base


class UserRole(Base):

    """
    用户-角色关联
    """

    __tablename__ = "user_roles"

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "role_id",
            name="uq_user_role",
        ),
    )

    id: Mapped[int] = mapped_column(
        primary_key=True,
        autoincrement=True
    )

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        index=True
    )

    role_id: Mapped[int] = mapped_column(
        BigInteger,
        index=True
    )
