from datetime import datetime

from sqlalchemy import String, BigInteger, Text, DateTime, Float, Integer, JSON, Index, func
from sqlalchemy.orm import Mapped, mapped_column

from work_agent.db.base import Base


class AgentLog(Base):

    """
    Agent 审计日志

    一次问答完整链路：
    用户信息 + 请求信息 + 输入输出 + 状态 + 性能 + 异常
    """

    __tablename__ = "agent_logs"

    __table_args__ = (
        # 高频查询：租户内按时间过滤
        Index(
            "ix_agent_logs_tenant_created",
            "tenant_id",
            "created_at",
        ),
        Index(
            "ix_agent_logs_created_at",
            "created_at",
        ),
    )

    id: Mapped[int] = mapped_column(
        primary_key=True,
        autoincrement=True
    )

    # 一次请求唯一标识
    request_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        unique=True,
        index=True
    )

    # 多租户占位，默认空表示单租户
    tenant_id: Mapped[str] = mapped_column(
        String(64),
        default="",
        index=True
    )

    user_id: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
        index=True
    )

    # 用户上下文快照（提问时刻的部门/角色）
    department: Mapped[str] = mapped_column(
        String(64),
        default=""
    )

    role: Mapped[str] = mapped_column(
        String(32),
        default=""
    )

    # 渠道：wechat / web / admin
    channel: Mapped[str] = mapped_column(
        String(16),
        default="wechat"
    )

    question: Mapped[str] = mapped_column(
        Text
    )

    answer: Mapped[str] = mapped_column(
        Text
    )

    # 用户意图（Agent 任务分析结果）
    intent: Mapped[str] = mapped_column(
        String(64),
        default=""
    )

    # processing / success / failed / denied
    status: Mapped[str] = mapped_column(
        String(32),
        default="processing"
    )

    error_type: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True
    )

    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True
    )

    # 命中的文档列表（JSON：source/score 等）
    retrieval_documents: Mapped[list | None] = mapped_column(
        JSON,
        nullable=True
    )

    # 性能
    latency_ms: Mapped[int] = mapped_column(
        Integer,
        default=0
    )

    token_usage: Mapped[int] = mapped_column(
        Integer,
        default=0
    )

    # 兼容旧字段
    tokens: Mapped[int] = mapped_column(
        default=0
    )

    cost_time: Mapped[float] = mapped_column(
        Float,
        default=0
    )

    # ======================
    # 智能体审计字段（P4-6）
    # ======================

    agent_version: Mapped[str] = mapped_column(
        String(32),
        default=""
    )

    model_name: Mapped[str] = mapped_column(
        String(64),
        default=""
    )

    prompt_version: Mapped[str] = mapped_column(
        String(32),
        default=""
    )

    intent_confidence: Mapped[float] = mapped_column(
        Float,
        default=0.0
    )

    # 调用的工具列表（JSON）
    tools_called: Mapped[list | None] = mapped_column(
        JSON,
        nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now()
    )

    # 生命周期：归档时间（非空表示已归档，默认列表不展示）
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
        index=True
    )
