from work_agent.db.session import SessionLocal
from work_agent.repositories.document_repository import DocumentRepository


class KnowledgeService:

    """
    知识服务

    封装向量检索，并回填文档信息
    纯召回，不调用 LLM
    """

    def __init__(
            self,
            embedding,
            store,
            document_repository: DocumentRepository | None = None
    ):

        self.embedding = embedding

        self.store = store

        self.document_repository = document_repository or DocumentRepository()


    def search(
            self,
            query: str,
            top_k: int = 5,
            filter: str = "",
            tenant_id: str | None = None
    ) -> list[dict]:

        """
        检索知识库，返回命中片段（含 document_id / document_filename）

        tenant_id 提供时（含空串"默认租户"）强制按租户隔离过滤
        """

        filters = []

        if filter:
            filters.append(filter)

        # 注意：空串也是有效租户（默认租户），必须用 is not None 判断
        if tenant_id is not None:
            filters.append(
                f'metadata["tenant_id"] == "{_escape(tenant_id)}"'
            )

        combined_filter = " && ".join(filters)

        vector = self.embedding.encode(
            [
                query
            ]
        )[0]

        hits = self.store.search_with_document(
            vector,
            top_k=top_k,
            filter=combined_filter
        )

        db = SessionLocal()

        try:

            for hit in hits:

                document_id = hit.get(
                    "document_id"
                )

                if not document_id:
                    continue

                document = self.document_repository.get_by_id(
                    db,
                    document_id
                )

                hit["document_filename"] = (
                    document.filename
                    if document
                    else ""
                )

        finally:

            db.close()

        return hits


def _escape(value: str) -> str:

    """
    Milvus filter 字符串字面量转义
    """

    return (
        value
        .replace("\\", "\\\\")
        .replace('"', '\\"')
    )
