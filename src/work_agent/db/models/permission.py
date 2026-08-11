from sqlalchemy import String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from work_agent.db.base import Base


class Permission(Base):

    """
    权限点
    """

    __tablename__ = "permissions"

    __table_args__ = (
        UniqueConstraint(
            "code",
            name="uq_permissions_code"
        ),
    )

    id: Mapped[int] = mapped_column(
        primary_key=True,
        autoincrement=True
    )

    # document:view / document:create / document:delete /
    # document:permission_manage / audit:view / system:manage
    code: Mapped[str] = mapped_column(
        String(64),
        index=True
    )

    name: Mapped[str] = mapped_column(
        String(64)
    )

    description: Mapped[str] = mapped_column(
        String(255),
        default=""
    )
