from work_agent.db.session import SessionLocal
from work_agent.document.parser import parse_document
from work_agent.knowledge.access import build_access_from_permission_rows
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
            embedding
    ):

        self.storage = storage

        self.store = store

        self.embedding = embedding

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
                    document.category,

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


            # 插入 Milvus（document_id 作为动态字段）
            milvus_ids = self.store.insert_documents(
                chunks,
                self.embedding,
                document_id=document.id,
                category=document.category,
                tenant_id=document.tenant_id
            )


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
