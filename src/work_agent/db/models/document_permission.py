from sqlalchemy import String, BigInteger, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from work_agent.db.base import Base


class DocumentPermission(Base):

    """
    文档权限

    public 文档：一条 department="ALL" 记录
    restricted 文档：每 department/role/user 一条记录
    """

    __tablename__ = "document_permission"

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

    document_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("documents.id"),
        index=True
    )

    department: Mapped[str] = mapped_column(
        String(64),
        default="ALL"
    )

    role: Mapped[str] = mapped_column(
        String(32),
        default=""
    )

    # 指定用户（可选）
    user_id: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
        index=True
    )
