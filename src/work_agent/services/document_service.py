from concurrent.futures import ThreadPoolExecutor

from work_agent.db.session import SessionLocal
from work_agent.document.pipeline import DocumentPipeline
from work_agent.repositories.document_repository import DocumentRepository
from work_agent.repositories.knowledge_chunk_repository import KnowledgeChunkRepository
from work_agent.repositories.document_permission_repository import DocumentPermissionRepository
from work_agent.storage.minio import MinioStorage, build_object_key
from work_agent.core.exceptions import TenantAccessDenied


# 后台管线执行器
# Phase2 换 Celery 时，仅需替换 DocumentService._dispatch 的实现
_PIPELINE_EXECUTOR = ThreadPoolExecutor(
    max_workers=2,
    thread_name_prefix="doc-pipeline"
)


def _file_type(filename: str) -> str:

    return (
        filename.rsplit(".", 1)[-1].lower()
        if "." in filename
        else ""
    )


class DocumentService:

    """
    文档业务编排

    upload 只做：建记录 → 存 MinIO → 异步投递管线 → 立即返回
    不占用 HTTP 请求生命周期
    """

    def __init__(
            self,
            storage: MinioStorage | None = None,
            store=None,
            embedding=None
    ):

        self.storage = storage or MinioStorage()

        self.store = store

        self.embedding = embedding

        self.pipeline = DocumentPipeline(
            self.storage,
            self.store,
            self.embedding
        )

        self.document_repository = DocumentRepository()

        self.chunk_repository = KnowledgeChunkRepository()

        self.permission_repository = DocumentPermissionRepository()


    def upload(
            self,
            *,
            filename: str,
            data: bytes,
            category: str,
            uploader: str,
            tenant_id: str = "",
            visibility: str = "public",
            departments: list[str] | None = None,
            roles: list[str] | None = None
    ):

        """
        上传文档

        返回 documents 记录（status=processing），管线异步跑
        """

        departments = departments or []

        roles = roles or []

        file_type = _file_type(filename)

        storage_path = build_object_key(
            tenant_id,
            filename
        )

        # 先存 MinIO，失败则不落库
        self.storage.ensure_bucket()

        self.storage.put_object(
            storage_path,
            data
        )

        db = SessionLocal()

        try:

            document = self.document_repository.create(
                db,
                tenant_id=tenant_id,
                filename=filename,
                file_type=file_type,
                storage_path=storage_path,
                category=category,
                uploader=uploader,
                visibility=visibility
            )

            self.permission_repository.bulk_create(
                db,
                document_id=document.id,
                departments=departments,
                roles=roles,
                tenant_id=tenant_id
            )

            # 异步投递管线
            self._dispatch(
                document.id
            )

            return document

        finally:

            db.close()


    def delete(
            self,
            document_id: int,
            tenant_id: str = ""
    ) -> bool:

        """
        删除文档

        顺序：按 knowledge_chunks.milvus_id 删 Milvus 向量（事实源）
             → 兜底按 document_id 动态字段删
             → 删 DB 记录（chunks/permissions/document）
             → 删 MinIO 对象
        """

        db = SessionLocal()

        try:

            document = self.document_repository.get_by_id(
                db,
                document_id
            )

            if not document:
                return False

            # 租户越权校验：不能删除其他租户的文档
            if document.tenant_id != tenant_id:

                raise TenantAccessDenied(
                    "无权删除该文档"
                )

            # 0. 先标记 deleting（提交），通知并发管线停止插入
            #    竞态防护：管线在插入前后各校验一次文档状态，
            #    标记删除后管线校验不通过 → 不产生 Milvus 孤儿向量
            self.document_repository.update_status(
                db,
                document_id,
                "deleting"
            )

            # 1. 按 milvus_id 删向量（唯一事实源）
            milvus_ids = self.chunk_repository.get_milvus_ids_by_document(
                db,
                document_id
            )

            if milvus_ids:

                self.store.delete_by_ids(
                    milvus_ids
                )

            # 2. 兜底：按 document_id 动态字段清理残留
            self.store.delete_by_document(
                document_id
            )

            # 3. 删 DB 记录
            self.chunk_repository.delete_by_document(
                db,
                document_id
            )

            self.permission_repository.delete_by_document(
                db,
                document_id
            )

            self.document_repository.delete(
                db,
                document_id
            )

            # 4. 删 MinIO 对象
            self.storage.remove_object(
                document.storage_path
            )

            return True

        finally:

            db.close()


    def list_documents(
            self,
            tenant_id: str = "",
            status: str | None = None,
            offset: int = 0,
            limit: int = 100
    ):

        """
        文档列表（含 chunk 数量）
        """

        db = SessionLocal()

        try:

            documents = self.document_repository.list(
                db,
                tenant_id=tenant_id,
                status=status,
                offset=offset,
                limit=limit
            )

            for document in documents:

                document.chunk_count = len(
                    self.chunk_repository.get_milvus_ids_by_document(
                        db,
                        document.id
                    )
                )

            return documents

        finally:

            db.close()


    def get_document(
            self,
            document_id: int,
            tenant_id: str = ""
    ):

        """
        文档详情（含权限与切片）
        """

        db = SessionLocal()

        try:

            document = self.document_repository.get_by_id(
                db,
                document_id
            )

            if not document:
                return None

            # 租户越权校验：不能查看其他租户的文档
            if document.tenant_id != tenant_id:

                raise TenantAccessDenied(
                    "无权查看该文档"
                )

            document.chunks = self.chunk_repository.get_by_document(
                db,
                document_id
            )

            document.permissions = self.permission_repository.get_by_document(
                db,
                document_id
            )

            return document

        finally:

            db.close()


    def _dispatch(
            self,
            document_id: int
    ) -> None:

        """
        异步投递管线

        Phase1：线程池
        Phase2（Celery 替换点）：
            celery_task.apply_async(args=[document_id])
        """

        _PIPELINE_EXECUTOR.submit(
            self.pipeline.process,
            document_id
        )
