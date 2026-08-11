from datetime import datetime

from sqlalchemy import String, BigInteger, DateTime, Index, func
from sqlalchemy.orm import Mapped, mapped_column

from work_agent.db.base import Base


class Conversation(Base):

    """
    会话表

    按 (tenant_id, user_id, channel) 追踪用户会话
    支持会话连续性、审计与后续多轮记忆
    """

    __tablename__ = "conversations"

    __table_args__ = (
        Index(
            "ix_conversations_tenant_user_channel",
            "tenant_id",
            "user_id",
            "channel",
        ),
    )

    id: Mapped[int] = mapped_column(
        primary_key=True,
        autoincrement=True
    )

    tenant_id: Mapped[str] = mapped_column(
        String(64),
        default="",
        index=True
    )

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        index=True
    )

    # wechat / web / admin
    channel: Mapped[str] = mapped_column(
        String(16),
        default="wechat"
    )

    # active / closed
    status: Mapped[str] = mapped_column(
        String(32),
        default="active"
    )

    message_count: Mapped[int] = mapped_column(
        default=0
    )

    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now()
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
