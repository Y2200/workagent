from sqlalchemy import BigInteger, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from work_agent.db.base import Base


class RolePermission(Base):

    """
    角色-权限关联
    """

    __tablename__ = "role_permissions"

    __table_args__ = (
        UniqueConstraint(
            "role_id",
            "permission_id",
            name="uq_role_permission",
        ),
    )

    id: Mapped[int] = mapped_column(
        primary_key=True,
        autoincrement=True
    )

    role_id: Mapped[int] = mapped_column(
        BigInteger,
        index=True
    )

    permission_id: Mapped[int] = mapped_column(
        BigInteger,
        index=True
    )
