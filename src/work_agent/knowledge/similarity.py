from work_agent.core.exceptions import TenantAccessDenied
from work_agent.db.session import SessionLocal
from work_agent.repositories.document_repository import DocumentRepository
from work_agent.repositories.knowledge_chunk_repository import KnowledgeChunkRepository


def _escape(value: str) -> str:

    """
    Milvus filter 字符串字面量转义
    """

    return (
        value
        .replace("\\", "\\\\")
        .replace('"', '\\"')
    )


class SimilarDocumentService:

    """
    相似文档检测

    对目标文档逐 chunk 做向量检索（同租户、排除自身），
    按命中文档聚合匹配块数与最高相似度，发现重复/高度相似文档。
    """

    def __init__(
            self,
            embedding=None,
            store=None,
            chunk_repository: KnowledgeChunkRepository | None = None,
            document_repository: DocumentRepository | None = None
    ):

        self.embedding = embedding

        self.store = store

        self.chunk_repository = (
            chunk_repository or KnowledgeChunkRepository()
        )

        self.document_repository = (
            document_repository or DocumentRepository()
        )


    def find_similar(
            self,
            document_id: int,
            tenant_id: str,
            threshold: float = 0.8,
            top_k: int = 5
    ) -> list[dict]:

        """
        返回相似文档列表

        [
            {
                "document_id": int,
                "filename": str,
                "matched_chunks": int,   # 命中目标文档的块数
                "max_score": float,      # 最高向量相似度
                "avg_score": float,
            }
        ]
        """

        db = SessionLocal()

        try:

            document = self.document_repository.get_by_id(
                db,
                document_id
            )

            if not document:
                raise ValueError(
                    f"文档不存在: {document_id}"
                )

            if document.tenant_id != tenant_id:
                raise TenantAccessDenied(
                    "无权检索该文档的相似文档"
                )

            chunks = self.chunk_repository.get_by_document(
                db,
                document_id
            )

        finally:

            db.close()

        if not chunks:
            return []

        filter_expr = (
            f'metadata["tenant_id"] == "{_escape(tenant_id)}"'
            f" && document_id != {document_id}"
        )

        # 其他文档 document_id → 命中统计
        hits: dict[int, dict] = {}

        for chunk in chunks:

            vector = self.embedding.encode(
                [chunk.content]
            )[0]

            results = self.store.search_with_document(
                vector,
                top_k=3,
                score_threshold=threshold,
                filter=filter_expr,
            )

            for item in results:

                other_id = item.get("document_id")

                if not other_id or other_id == document_id:
                    continue

                score = item.get("score", 0.0)

                entry = hits.setdefault(
                    other_id,
                    {
                        "matched_chunks": 0,
                        "max_score": 0.0,
                        "score_sum": 0.0,
                    },
                )

                entry["matched_chunks"] += 1

                entry["max_score"] = max(
                    entry["max_score"],
                    score
                )

                entry["score_sum"] += score

        if not hits:
            return []

        db = SessionLocal()

        try:

            results = []

            for other_id, entry in hits.items():

                other = self.document_repository.get_by_id(
                    db,
                    other_id
                )

                if not other:
                    continue

                avg_score = (
                    entry["score_sum"]
                    / entry["matched_chunks"]
                )

                results.append(
                    {
                        "document_id": other_id,
                        "filename": other.filename,
                        "matched_chunks": entry["matched_chunks"],
                        "max_score": round(
                            entry["max_score"],
                            4
                        ),
                        "avg_score": round(
                            avg_score,
                            4
                        ),
                    }
                )

        finally:

            db.close()

        # 按命中块数降序，其次最高相似度降序
        results.sort(
            key=lambda item: (
                item["matched_chunks"],
                item["max_score"],
            ),
            reverse=True,
        )

        return results[:top_k]
