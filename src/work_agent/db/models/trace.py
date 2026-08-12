from datetime import datetime

from sqlalchemy import (
    BigInteger,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    DateTime,
    JSON,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from work_agent.db.base import Base


class AgentTrace(Base):

    """
    一次 Agent 执行的链路追踪（根）

    请求级 trace：状态/总耗时/span 数
    """

    __tablename__ = "agent_traces"

    __table_args__ = (
        Index(
            "ix_agent_traces_tenant_created",
            "tenant_id",
            "created_at",
        ),
    )

    id: Mapped[int] = mapped_column(
        primary_key=True,
        autoincrement=True
    )

    # 一次请求唯一标识（与 agent_logs.request_id 对齐）
    request_id: Mapped[str] = mapped_column(
        String(64),
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

    channel: Mapped[str] = mapped_column(
        String(16),
        default="wechat"
    )

    # ok / error
    status: Mapped[str] = mapped_column(
        String(16),
        default="ok"
    )

    total_duration_ms: Mapped[int] = mapped_column(
        Integer,
        default=0
    )

    span_count: Mapped[int] = mapped_column(
        Integer,
        default=0
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now()
    )


class TraceSpan(Base):

    """
    单个追踪片段（span）

    记录某阶段的耗时/状态/属性；parent_span_id 构成瀑布
    """

    __tablename__ = "trace_spans"

    __table_args__ = (
        Index(
            "ix_trace_spans_trace",
            "trace_id",
        ),
        Index(
            "ix_trace_spans_tenant",
            "tenant_id",
        ),
    )

    id: Mapped[int] = mapped_column(
        primary_key=True,
        autoincrement=True
    )

    # 所属 trace
    trace_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("agent_traces.id"),
        index=True
    )

    tenant_id: Mapped[str] = mapped_column(
        String(64),
        default="",
        index=True
    )

    # 阶段标识（intent_router / planner / supervisor / tool.xxx）
    span_id: Mapped[str] = mapped_column(
        String(64),
        default=""
    )

    parent_span_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True
    )

    name: Mapped[str] = mapped_column(
        String(128)
    )

    # 组件分类：context_builder/intent_router/planner/supervisor/tool/audit
    component: Mapped[str] = mapped_column(
        String(32),
        default=""
    )

    duration_ms: Mapped[int] = mapped_column(
        Integer,
        default=0
    )

    # ok / error
    status: Mapped[str] = mapped_column(
        String(16),
        default="ok"
    )

    error_type: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True
    )

    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True
    )

    # 阶段属性（工具名/模型名/意图等）
    attributes: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now()
    )
