from datetime import datetime

from sqlalchemy import String, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from work_agent.db.base import Base


class Tenant(Base):

    """
    企业租户表
    """

    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(
        primary_key=True,
        autoincrement=True
    )

    name: Mapped[str] = mapped_column(
        String(128)
    )

    # 企业微信 corp_id
    corp_id: Mapped[str] = mapped_column(
        String(128),
        unique=True,
        index=True
    )

    # active / disabled
    status: Mapped[str] = mapped_column(
        String(32),
        default="active"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now()
    )

    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=True
    )
