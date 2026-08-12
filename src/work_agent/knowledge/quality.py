from work_agent.db.session import SessionLocal
from work_agent.repositories.document_repository import DocumentRepository
from work_agent.repositories.knowledge_chunk_repository import KnowledgeChunkRepository
from work_agent.repositories.knowledge_graph_repository import (
    KnowledgeEntityRepository,
)
from work_agent.knowledge.similarity import SimilarDocumentService


# 质量体检限制：重复扫描前 N 篇文档（控制 LLM/向量检索成本）
_DUPLICATE_SCAN_LIMIT = 20

# chunk 长度阈值
_SHORT_CHUNK_CHARS = 20

_LONG_CHUNK_CHARS = 1500


class KnowledgeQualityService:

    """
    知识质量分析

    从覆盖/一致性/分类/重复/健康度维度体检知识库（按租户隔离）
    """

    def __init__(
            self,
            document_repository: DocumentRepository | None = None,
            chunk_repository: KnowledgeChunkRepository | None = None,
            entity_repository: KnowledgeEntityRepository | None = None,
            similar_service: SimilarDocumentService | None = None
    ):

        self.document_repository = (
            document_repository or DocumentRepository()
        )

        self.chunk_repository = (
            chunk_repository or KnowledgeChunkRepository()
        )

        self.entity_repository = (
            entity_repository or KnowledgeEntityRepository()
        )

        self.similar_service = similar_service


    def analyze(
            self,
            tenant_id: str,
            scan_limit: int = _DUPLICATE_SCAN_LIMIT
    ) -> dict:

        """
        生成质量报告
        """

        db = SessionLocal()

        try:

            documents = self.document_repository.list(
                db,
                tenant_id=tenant_id,
                limit=10000,
            )

            # 加载每篇文档的 chunk（仅 ready 文档）
            doc_data = []

            for document in documents:

                chunks = (
                    self.chunk_repository.get_by_document(
                        db,
                        document.id
                    )
                    if document.status == "ready"
                    else []
                )

                doc_data.append(
                    {
                        "id": document.id,
                        "filename": document.filename,
                        "status": document.status,
                        "category": document.category or "",
                        "chunk_count": len(chunks),
                        "chunks": chunks,
                    }
                )

            entities = self.entity_repository.count_by_tenant(
                db,
                tenant_id
            )

        finally:

            db.close()

        overview = self._overview(
            doc_data,
            entities,
        )

        chunk_stats = self._chunk_stats(
            doc_data,
        )

        chunk_length = self._chunk_length(
            doc_data,
        )

        classification = self._classification(
            doc_data,
        )

        consistency = self._consistency(
            doc_data,
            tenant_id,
        )

        duplicates = self._duplicates(
            doc_data,
            tenant_id,
            scan_limit,
        )

        health_score = self._health_score(
            overview,
            chunk_length,
            consistency,
            classification,
        )

        return {
            "tenant_id": tenant_id,
            "overview": overview,
            "chunk_stats": chunk_stats,
            "chunk_length": chunk_length,
            "classification": classification,
            "duplicates": duplicates,
            "consistency": consistency,
            "health_score": health_score,
        }


    # ======================
    # 各维度统计
    # ======================

    @staticmethod
    def _overview(
            doc_data: list[dict],
            entities: int
    ) -> dict:

        statuses = {}

        total_chunks = 0

        for doc in doc_data:

            statuses[doc["status"]] = (
                statuses.get(doc["status"], 0) + 1
            )

            total_chunks += doc["chunk_count"]

        return {
            "total_documents": len(doc_data),
            "ready": statuses.get("ready", 0),
            "processing": statuses.get("processing", 0),
            "failed": statuses.get("failed", 0),
            "total_chunks": total_chunks,
            "total_entities": entities,
        }


    @staticmethod
    def _chunk_stats(
            doc_data: list[dict]
    ) -> dict:

        counts = [
            doc["chunk_count"]
            for doc in doc_data
            if doc["chunk_count"] > 0
        ]

        if not counts:

            return {
                "per_document_min": 0,
                "per_document_max": 0,
                "per_document_avg": 0.0,
                "single_chunk_documents": [],
            }

        single_chunk = [
            {
                "document_id": doc["id"],
                "filename": doc["filename"],
            }
            for doc in doc_data
            if doc["chunk_count"] == 1
        ]

        return {
            "per_document_min": min(counts),
            "per_document_max": max(counts),
            "per_document_avg": round(
                sum(counts) / len(counts),
                2
            ),
            "single_chunk_documents": single_chunk,
        }


    @staticmethod
    def _chunk_length(
            doc_data: list[dict]
    ) -> dict:

        empty = 0

        short = 0

        long = 0

        total_chars = 0

        total_chunks = 0

        for doc in doc_data:

            for chunk in doc["chunks"]:

                content = chunk.content or ""

                length = len(content)

                total_chars += length

                total_chunks += 1

                if not content.strip():
                    empty += 1

                elif length < _SHORT_CHUNK_CHARS:
                    short += 1

                elif length > _LONG_CHUNK_CHARS:
                    long += 1

        return {
            "total_chunks": total_chunks,
            "empty_chunks": empty,
            "short_chunks": short,
            "long_chunks": long,
            "avg_chunk_chars": round(
                total_chars / total_chunks,
                1
            )
            if total_chunks
            else 0.0,
        }


    @staticmethod
    def _classification(
            doc_data: list[dict]
    ) -> dict:

        unclassified = []

        category_counts: dict[str, int] = {}

        for doc in doc_data:

            category = doc["category"].strip()

            if not category or category == "未分类":

                unclassified.append(
                    {
                        "document_id": doc["id"],
                        "filename": doc["filename"],
                    }
                )

            else:

                category_counts[category] = (
                    category_counts.get(category, 0) + 1
                )

        distribution = [
            {
                "name": name,
                "count": count,
            }
            for name, count in sorted(
                category_counts.items(),
                key=lambda item: item[1],
                reverse=True,
            )
        ]

        return {
            "unclassified_documents": len(unclassified),
            "unclassified_list": unclassified,
            "categories": distribution,
        }


    def _consistency(
            self,
            doc_data: list[dict],
            tenant_id: str
    ) -> dict:

        """
        校验 DB chunk 记录与 Milvus 向量一致性
        """

        from work_agent.core.container import rag_service

        store = rag_service.store

        # 1. DB 有记录但 Milvus 数量不符
        mismatched = []

        db_chunk_ids = set()

        for doc in doc_data:

            if doc["chunk_count"] == 0:
                continue

            try:

                milvus_count = store.count_by_document(
                    doc["id"]
                )

            except Exception:

                milvus_count = -1

            for chunk in doc["chunks"]:
                db_chunk_ids.add(
                    chunk.milvus_id
                )

            if milvus_count != doc["chunk_count"]:

                mismatched.append(
                    {
                        "document_id": doc["id"],
                        "filename": doc["filename"],
                        "db_chunks": doc["chunk_count"],
                        "milvus_chunks": milvus_count,
                    }
                )

        # 2. Milvus 孤儿向量（有向量无 DB 记录）
        orphan_vectors = 0

        try:

            rows = store.client.query(
                collection_name=store.COLLECTION_NAME,
                filter=(
                    f'metadata["tenant_id"] == "{tenant_id}"'
                ),
                output_fields=["id"],
                limit=16384,
                consistency_level="Strong",
            )

            milvus_ids = {
                row["id"]
                for row in rows
            }

            orphan_vectors = len(
                milvus_ids - db_chunk_ids
            )

        except Exception:

            orphan_vectors = -1

        return {
            "mismatched_documents": mismatched,
            "db_documents_without_vectors": len(mismatched),
            "milvus_orphan_vectors": max(orphan_vectors, 0),
            "consistent": (
                not mismatched
                and orphan_vectors == 0
            ),
        }


    def _duplicates(
            self,
            doc_data: list[dict],
            tenant_id: str,
            scan_limit: int
    ) -> dict:

        """
        抽样检测相似文档对（复用相似文档服务）
        """

        if self.similar_service is None:
            return {
                "sampled": 0,
                "pairs": [],
            }

        ready_docs = [
            doc
            for doc in doc_data
            if doc["chunk_count"] > 0
        ]

        sampled = ready_docs[:scan_limit]

        seen_pairs = set()

        pairs = []

        for doc in sampled:

            try:

                similar = self.similar_service.find_similar(
                    doc["id"],
                    tenant_id,
                    threshold=0.8,
                    top_k=3,
                )

            except Exception:

                continue

            for item in similar:

                key = tuple(
                    sorted(
                        (doc["id"], item["document_id"])
                    )
                )

                if key in seen_pairs:
                    continue

                seen_pairs.add(key)

                pairs.append(
                    {
                        "document_a": key[0],
                        "document_b": key[1],
                        "filename_a": doc["filename"],
                        "filename_b": item["filename"],
                        "max_score": item["max_score"],
                        "matched_chunks": item["matched_chunks"],
                    }
                )

        pairs.sort(
            key=lambda item: item["max_score"],
            reverse=True,
        )

        return {
            "sampled": len(sampled),
            "pairs": pairs[:10],
        }


    @staticmethod
    def _health_score(
            overview: dict,
            chunk_length: dict,
            consistency: dict,
            classification: dict
    ) -> int:

        """
        健康度 0-100

        失败文档/空 chunk/孤儿向量/未分类文档按权重扣分
        """

        score = 100.0

        score -= overview["failed"] * 5

        score -= chunk_length["empty_chunks"] * 2

        score -= classification["unclassified_documents"]

        score -= consistency["milvus_orphan_vectors"]

        score -= consistency["db_documents_without_vectors"] * 3

        return int(
            max(0, min(100, score))
        )
