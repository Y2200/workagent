from datetime import datetime

from sqlalchemy import String, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from work_agent.db.base import Base


class User(Base):

    """
    用户表
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(
        primary_key=True,
        autoincrement=True
    )

    # 多租户占位，默认空表示单租户
    tenant_id: Mapped[str] = mapped_column(
        String(64),
        default="",
        index=True
    )

    wechat_user_id: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
        index=True
    )

    username: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        index=True
    )

    department: Mapped[str] = mapped_column(
        String(64),
        default=""
    )

    role: Mapped[str] = mapped_column(
        String(32),
        default="员工"
    )

    password_hash: Mapped[str] = mapped_column(
        String(255)
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now()
    )
