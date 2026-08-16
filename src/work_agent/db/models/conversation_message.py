from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from work_agent.db.base import Base


class ConversationMessage(Base):

    """
    会话消息表（Enterprise Agent 会话记忆，Phase 1）

    保存完整对话历史，**不物理删除**（完整会话留存）。
    context window（最近 N 轮）由 conversation_memory_service 读取时限制。

    - role: user / assistant / tool / system（tool 预留未来工具 trace）
    - scope: chat / task / tool / system（为 chat/task/tool/system 分离预留）
    - tool_name / metadata: 未来工具调用 trace 与审计扩展
    - BaseMessage 仅存在于运行态，本表存原始字段，由 adapter 转换
    """

    __tablename__ = "conversation_messages"

    __table_args__ = (
        Index(
            "ix_conversation_messages_conversation_id",
            "conversation_id",
        ),
        Index(
            "ix_conversation_messages_conversation_scope",
            "conversation_id",
            "scope",
        ),
    )

    id: Mapped[int] = mapped_column(
        primary_key=True,
        autoincrement=True
    )

    # 稳定 per-user 会话键（conversations.id，runtime 注入）
    conversation_id: Mapped[int] = mapped_column(
        BigInteger,
        index=True
    )

    # user / assistant / tool / system
    role: Mapped[str] = mapped_column(
        String(16),
        default="user"
    )

    # chat / task / tool / system（memory scope 分离预留）
    scope: Mapped[str] = mapped_column(
        String(16),
        default="chat"
    )

    content: Mapped[str] = mapped_column(
        Text
    )

    # 工具名（role=tool 时，未来工具 trace）
    tool_name: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True
    )

    # 工具调用元数据 / 审计扩展（JSON）
    # 注：SQLAlchemy Declarative 保留 metadata，故列名用 extra
    extra: Mapped[dict | None] = mapped_column(
        "extra",
        JSON,
        nullable=True
    )

    # 审计/清理冗余（隔离靠 conversation_id，tenant 仅便于审计）
    tenant_id: Mapped[str] = mapped_column(
        String(64),
        default="",
        index=True
    )

    user_id: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now()
    )
