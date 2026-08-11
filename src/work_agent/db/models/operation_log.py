from datetime import datetime

from sqlalchemy import String, BigInteger, DateTime, Index, func
from sqlalchemy.orm import Mapped, mapped_column

from work_agent.db.base import Base


class OperationLog(Base):

    """
    企业操作审计日志

    记录：登录成功/失败、上传文档、删除文档、修改权限、导出数据等
    """

    __tablename__ = "operation_logs"

    __table_args__ = (
        # 高频查询：租户内按时间过滤
        Index(
            "ix_operation_logs_tenant_created",
            "tenant_id",
            "created_at",
        ),
        Index(
            "ix_operation_logs_created_at",
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

    user_id: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
        index=True
    )

    # auth.login / auth.login_failed / document.create / document.delete /
    # document.permission_update / data.export
    action: Mapped[str] = mapped_column(
        String(64),
        index=True
    )

    target_type: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True
    )

    target_id: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True
    )

    ip: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True
    )

    user_agent: Mapped[str | None] = mapped_column(
        String(512),
        nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now()
    )
