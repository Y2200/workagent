from datetime import datetime

from sqlalchemy import String, Text, DateTime, Index, func
from sqlalchemy.orm import Mapped, mapped_column

from work_agent.db.base import Base


class Document(Base):

    """
    文件表
    """

    __tablename__ = "documents"

    __table_args__ = (
        # 高频查询：租户内按状态过滤
        Index(
            "ix_documents_tenant_status",
            "tenant_id",
            "status",
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

    filename: Mapped[str] = mapped_column(
        String(255)
    )

    file_type: Mapped[str] = mapped_column(
        String(16)
    )

    # MinIO 对象 key
    storage_path: Mapped[str] = mapped_column(
        String(512)
    )

    category: Mapped[str] = mapped_column(
        String(128),
        default=""
    )

    uploader: Mapped[str] = mapped_column(
        String(64),
        default=""
    )

    # 可见范围：public 全员 / restricted 按部门角色
    visibility: Mapped[str] = mapped_column(
        String(32),
        default="public"
    )

    # processing / ready / failed
    status: Mapped[str] = mapped_column(
        String(32),
        default="processing"
    )

    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True
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
