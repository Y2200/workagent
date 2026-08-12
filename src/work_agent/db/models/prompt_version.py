from datetime import datetime

from sqlalchemy import String, Text, DateTime, JSON, UniqueConstraint, Index, func
from sqlalchemy.orm import Mapped, mapped_column

from work_agent.db.base import Base


class PromptVersion(Base):

    """
    Prompt 版本（生命周期治理）

    状态流转：draft → approved → active（唯一）→ deprecated
    tenant_id="" 为平台级 Prompt（默认）；未来支持租户自定义
    """

    __tablename__ = "prompt_versions"

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "name",
            "version",
            name="uq_prompt_version_tenant_name_ver",
        ),
        Index(
            "ix_prompt_versions_name",
            "name",
        ),
        Index(
            "ix_prompt_versions_tenant_status",
            "tenant_id",
            "status",
        ),
    )

    id: Mapped[int] = mapped_column(
        primary_key=True,
        autoincrement=True
    )

    # "" = 平台级
    tenant_id: Mapped[str] = mapped_column(
        String(64),
        default="",
        index=True
    )

    name: Mapped[str] = mapped_column(
        String(128)
    )

    version: Mapped[str] = mapped_column(
        String(32)
    )

    content: Mapped[str] = mapped_column(
        Text
    )

    # draft / approved / active / deprecated
    status: Mapped[str] = mapped_column(
        String(16),
        default="draft"
    )

    # Prompt 变量（来自 metadata 注册表）
    variables: Mapped[list | None] = mapped_column(
        JSON,
        nullable=True
    )

    description: Mapped[str] = mapped_column(
        String(255),
        default=""
    )

    updated_by: Mapped[str] = mapped_column(
        String(64),
        default=""
    )

    activated_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now()
    )
