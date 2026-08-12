from datetime import datetime

from sqlalchemy import BigInteger, String, Float, DateTime, Integer, Index, func
from sqlalchemy.orm import Mapped, mapped_column

from work_agent.db.base import Base


class LLMCostRecord(Base):

    """
    LLM 成本记账（按租户）

    每次 Agent 执行完成后写入一笔成本记录
    """

    __tablename__ = "llm_cost_records"

    __table_args__ = (
        Index(
            "ix_llm_cost_tenant_created",
            "tenant_id",
            "created_at",
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

    # 关联的 Agent 请求
    request_id: Mapped[str] = mapped_column(
        String(64),
        default="",
        index=True
    )

    user_id: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
        index=True
    )

    model: Mapped[str] = mapped_column(
        String(64),
        default=""
    )

    input_tokens: Mapped[int] = mapped_column(
        Integer,
        default=0
    )

    output_tokens: Mapped[int] = mapped_column(
        Integer,
        default=0
    )

    total_tokens: Mapped[int] = mapped_column(
        Integer,
        default=0
    )

    # 估算成本（元）
    cost: Mapped[float] = mapped_column(
        Float,
        default=0.0
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now()
    )
