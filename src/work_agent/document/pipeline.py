from work_agent.config import settings
from work_agent.db.session import SessionLocal
from work_agent.document.parser import parse_document
from work_agent.knowledge.access import build_access_from_permission_rows
from work_agent.knowledge.classifier import DocumentClassifier
from work_agent.rag.splitter import split_documents
from work_agent.repositories.document_repository import DocumentRepository
from work_agent.repositories.knowledge_chunk_repository import KnowledgeChunkRepository
from work_agent.repositories.document_permission_repository import DocumentPermissionRepository


class DocumentPipeline:

    """
    文档入库管线

    解析 → 切分 → Embedding → Milvus → DB 记录

    由后台线程独立执行，每次独立开 Session
    """

    def __init__(
            self,
            storage,
            store,
            embedding,
            classifier: DocumentClassifier | None = None
    ):

        self.storage = storage

        self.store = store

        self.embedding = embedding

        # 自动分类器（失败回退，不阻塞入库）
        self.classifier = classifier or DocumentClassifier()

        self.document_repository = DocumentRepository()

        self.chunk_repository = KnowledgeChunkRepository()

        self.permission_repository = DocumentPermissionRepository()


    def process(
            self,
            document_id: int
    ) -> None:

        """
        处理单个文档

        任何一步失败：status=failed + 回滚已插入的 Milvus 向量
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


            raw = self.storage.get_object_bytes(
                document.storage_path
            )

            parsed = parse_document(
                document.filename,
                raw
            )

            # 自动分类（失败回退到人工类别/未分类，不阻塞入库）
            category = self._classify(
                db,
                document,
                parsed.content,
            )

            # 组装权限元数据（与 rag/permission.py 的 PermissionFilter 兼容）
            access = self._build_access(
                db,
                document.id
            )

            metadata = {
                "document_id":
                    document.id,

                "title":
                    document.filename,

                "category":
                    category,

                "access":
                    access,

                "tenant_id":
                    document.tenant_id
            }


            chunks = split_documents(
                [
                    {
                        "filename":
                            document.filename,

                        "content":
                            parsed.content,

                        "metadata":
                            metadata
                    }
                ]
            )


            # 竞态防护：插入前校验文档仍存在（未删除/未标记 deleting）
            # Web 上传后管线异步执行，用户可能在处理中删除文档；
            # 若不校验，删除先完成、管线后插入 → Milvus 孤儿向量（PG 已删、向量残留）
            if not self._is_active(document_id):
                print(
                    f"文档已被删除，跳过向量插入: {document_id}"
                )
                return

            # 插入 Milvus（document_id 作为动态字段）
            milvus_ids = self.store.insert_documents(
                chunks,
                self.embedding,
                document_id=document.id,
                category=category,
                tenant_id=document.tenant_id
            )


            # 竞态防护：插入后、落库前二次校验。
            # 若删除恰好在 insert 之后发生，回滚刚插入的 Milvus 向量，避免孤儿
            if not self._is_active(document.id):
                print(
                    f"文档在向量插入后被删除，回滚: {document.id}"
                )
                try:
                    self.store.delete_by_document(document.id)
                except Exception:
                    pass
                return

            # knowledge_chunks 是向量映射事实源
            self.chunk_repository.bulk_create(
                db,
                document_id=document.id,
                milvus_ids=milvus_ids,
                contents=[
                    chunk["text"]
                    for chunk in chunks
                ],
                tenant_id=document.tenant_id
            )


            self.document_repository.update_status(
                db,
                document.id,
                "ready"
            )

            print(
                f"文档管线完成: "
                f"document_id={document.id}, "
                f"chunks={len(chunks)}"
            )

        except Exception as exc:

            db.rollback()

            self._mark_failed(
                db,
                document_id,
                str(exc)
            )

            # 兜底回滚已插入的 Milvus 向量
            try:
                self.store.delete_by_document(
                    document_id
                )

            except Exception:
                pass

            raise

        finally:

            db.close()


    def _is_active(
            self,
            document_id: int
    ) -> bool:

        """
        独立 Session 校验文档是否仍处于活跃状态

        删除操作先把 status 置为 deleting，再删 Milvus/DB；
        管线在插入前后各校验一次，防止「删除先完成、管线后插入」产生 Milvus 孤儿向量
        """

        probe = SessionLocal()

        try:

            doc = self.document_repository.get_by_id(
                probe,
                document_id
            )

            return (
                doc is not None
                and doc.status not in ("deleting", "deleted")
            )

        finally:

            probe.close()


    def _classify(
            self,
            db,
            document,
            content: str
    ) -> str:

        """
        自动分类文档

        人工指定类别优先，仅在类别为空时触发自动分类（减少 LLM 调用）。
        开关关闭或分类失败 → 沿用原类别/未分类。
        命中时同步更新 DB 记录，Milvus 使用新类别
        """

        if not settings.knowledge_auto_classify:

            return document.category or ""

        if document.category and document.category.strip():

            # 人工类别优先，不覆盖
            return document.category

        category = self.classifier.classify(
            title=document.filename,
            content=content,
            fallback=document.category or "未分类",
        )

        if category and category != document.category:

            try:

                self.document_repository.update_category(
                    db,
                    document.id,
                    category,
                )

            except Exception:

                # 分类落库失败不阻塞主流程
                pass

        return category


    def _build_access(
            self,
            db,
            document_id: int
    ) -> dict:

        """
        从 document_permission 构建 access 元数据
        """

        permissions = self.permission_repository.get_by_document(
            db,
            document_id
        )

        return build_access_from_permission_rows(
            permissions
        )


    def _mark_failed(
            self,
            db,
            document_id: int,
            message: str
    ) -> None:

        try:

            self.document_repository.update_status(
                db,
                document_id,
                "failed",
                message
            )

        except Exception:
            pass
