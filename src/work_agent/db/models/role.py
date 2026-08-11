from datetime import datetime

from sqlalchemy import String, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from work_agent.db.base import Base


class Role(Base):

    """
    角色
    """

    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(
        primary_key=True,
        autoincrement=True
    )

    # 平台级角色 tenant_id=""；租户级角色为具体租户
    tenant_id: Mapped[str] = mapped_column(
        String(64),
        default="",
        index=True
    )

    # SUPER_ADMIN / TENANT_ADMIN / DEPARTMENT_ADMIN / USER
    code: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        index=True
    )

    name: Mapped[str] = mapped_column(
        String(64)
    )

    description: Mapped[str] = mapped_column(
        String(255),
        default=""
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now()
    )
