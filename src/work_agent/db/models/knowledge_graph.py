from datetime import datetime

from sqlalchemy import (
    BigInteger,
    ForeignKey,
    Index,
    String,
    Text,
    DateTime,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from work_agent.db.base import Base


class KnowledgeEntity(Base):

    """
    知识图谱实体（概念级）

    (tenant_id, name) 唯一：同名概念跨文档合并为一个节点
    """

    __tablename__ = "knowledge_entities"

    __table_args__ = (
        # 租户内按名称去重
        UniqueConstraint(
            "tenant_id",
            "name",
            name="uq_knowledge_entity_tenant_name",
        ),
        Index(
            "ix_knowledge_entities_tenant",
            "tenant_id",
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

    name: Mapped[str] = mapped_column(
        String(255)
    )

    # 实体类型：制度/流程/角色/概念/部门 等
    entity_type: Mapped[str] = mapped_column(
        String(32),
        default="概念"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now()
    )


class KnowledgeRelation(Base):

    """
    知识图谱关系（有向边）

    来源文档 document_id 记录出处，重建图谱时按文档清理
    """

    __tablename__ = "knowledge_relations"

    __table_args__ = (
        Index(
            "ix_knowledge_relations_tenant",
            "tenant_id",
        ),
        Index(
            "ix_knowledge_relations_document",
            "document_id",
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

    # 来源文档（按文档重建图谱时依据）
    document_id: Mapped[int] = mapped_column(
        BigInteger,
        default=0,
        index=True
    )

    # 起始实体
    source_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("knowledge_entities.id"),
        index=True
    )

    # 目标实体
    target_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("knowledge_entities.id"),
        index=True
    )

    # 关系类型：属于/相关/流程/依据 等
    relation: Mapped[str] = mapped_column(
        String(64),
        default="相关"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now()
    )
