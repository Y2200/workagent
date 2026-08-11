from sqlalchemy.orm import Session

from work_agent.db.models import KnowledgeChunk


class KnowledgeChunkRepository:

    """
    知识块数据访问

    knowledge_chunks 是 Milvus 向量映射的唯一事实源
    """

    def bulk_create(
            self,
            db: Session,
            *,
            document_id: int,
            milvus_ids: list[int],
            contents: list[str],
            tenant_id: str = ""
    ) -> None:

        for index, (milvus_id, content) in enumerate(
                zip(milvus_ids, contents)
        ):

            db.add(
                KnowledgeChunk(
                    tenant_id=tenant_id,
                    document_id=document_id,
                    milvus_id=milvus_id,
                    content=content,
                    chunk_index=index
                )
            )

        db.commit()


    def get_by_document(
            self,
            db: Session,
            document_id: int
    ):

        return (
            db.query(KnowledgeChunk)
            .filter(KnowledgeChunk.document_id == document_id)
            .order_by(KnowledgeChunk.chunk_index)
            .all()
        )


    def get_milvus_ids_by_document(
            self,
            db: Session,
            document_id: int
    ) -> list[int]:

        rows = (
            db.query(KnowledgeChunk.milvus_id)
            .filter(KnowledgeChunk.document_id == document_id)
            .all()
        )

        return [
            row[0]
            for row in rows
        ]


    def delete_by_document(
            self,
            db: Session,
            document_id: int
    ) -> None:

        db.query(KnowledgeChunk).filter(
            KnowledgeChunk.document_id == document_id
        ).delete(
            synchronize_session=False
        )

        db.commit()
