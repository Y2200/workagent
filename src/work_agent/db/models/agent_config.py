from datetime import datetime

from sqlalchemy import String, DateTime, JSON, UniqueConstraint, Index, func
from sqlalchemy.orm import Mapped, mapped_column

from work_agent.db.base import Base


class AgentConfig(Base):

    """
    Agent 配置项

    tenant_id="" 表示平台级默认；其他值表示租户级覆盖。
    (tenant_id, config_key) 唯一。
    """

    __tablename__ = "agent_configs"

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "config_key",
            name="uq_agent_config_tenant_key",
        ),
        Index(
            "ix_agent_configs_tenant",
            "tenant_id",
        ),
    )

    id: Mapped[int] = mapped_column(
        primary_key=True,
        autoincrement=True
    )

    # 多租户占位，"" = 平台级
    tenant_id: Mapped[str] = mapped_column(
        String(64),
        default="",
        index=True
    )

    config_key: Mapped[str] = mapped_column(
        String(128)
    )

    # JSON 值（支持标量/列表/字典）
    config_value: Mapped[object | None] = mapped_column(
        JSON,
        nullable=True
    )

    description: Mapped[str] = mapped_column(
        String(255),
        default=""
    )

    # 最后修改人
    updated_by: Mapped[str] = mapped_column(
        String(64),
        default=""
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
