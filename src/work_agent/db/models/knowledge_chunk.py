from sqlalchemy import String, BigInteger, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from work_agent.db.base import Base


class KnowledgeChunk(Base):

    """
    知识块

    knowledge_chunks 是 Milvus 向量映射的唯一事实源
    """

    __tablename__ = "knowledge_chunks"

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

    # Milvus 主键 id，删除向量时依据
    milvus_id: Mapped[int] = mapped_column(
        BigInteger,
        index=True
    )

    content: Mapped[str] = mapped_column(
        Text
    )

    chunk_index: Mapped[int] = mapped_column(
        default=0
    )
