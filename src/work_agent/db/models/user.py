from datetime import datetime

from sqlalchemy import Index, String, DateTime, func, text
from sqlalchemy.orm import Mapped, mapped_column

from work_agent.db.base import Base


class User(Base):

    """
    用户表
    """

    __tablename__ = "users"

    # 1 企微号 ↔ 1 用户（部分唯一索引：NULL 不受限）
    __table_args__ = (
        Index(
            "ix_users_wechat_user_id_unique",
            "wechat_user_id",
            unique=True,
            postgresql_where=text(
                "wechat_user_id IS NOT NULL"
            ),
        ),
    )

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

    # 显示名（可重复；同名员工靠 username/wechat_user_id 唯一区分）
    real_name: Mapped[str] = mapped_column(
        String(64),
        default=""
    )

    department: Mapped[str] = mapped_column(
        String(64),
        default=""
    )

    # 邮箱（邮件通知用，Phase 4）
    email: Mapped[str] = mapped_column(
        String(128),
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
