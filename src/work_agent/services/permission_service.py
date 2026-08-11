from work_agent.core.exceptions import TenantAccessDenied
from work_agent.db.session import SessionLocal
from work_agent.knowledge.access import build_access_from_permission_rows
from work_agent.repositories.document_permission_repository import DocumentPermissionRepository
from work_agent.repositories.document_repository import DocumentRepository


class PermissionService:

    """
    文档权限管理

    更新权限 → 数据库 document_permission + documents.visibility
             → 同步 Milvus chunk metadata（RAG 过滤即时生效）
    """

    def __init__(
            self,
            store,
            document_repository: DocumentRepository | None = None,
            permission_repository: DocumentPermissionRepository | None = None
    ):

        self.store = store

        self.document_repository = document_repository or DocumentRepository()

        self.permission_repository = permission_repository or DocumentPermissionRepository()


    def get_permissions(
            self,
            document_id: int,
            tenant_id: str
    ):

        db = SessionLocal()

        try:

            document = self.document_repository.get_by_id(
                db,
                document_id
            )

            if not document:
                return None

            if document.tenant_id != tenant_id:

                raise TenantAccessDenied(
                    "无权查看该文档权限"
                )

            rows = self.permission_repository.get_by_document(
                db,
                document_id
            )

            return {
                "visibility": document.visibility,
                "departments": sorted({
                    row.department
                    for row in rows
                    if row.department
                }),
                "roles": sorted({
                    row.role
                    for row in rows
                    if row.role
                }),
                "user_ids": sorted({
                    int(row.user_id)
                    for row in rows
                    if row.user_id is not None
                }),
            }

        finally:

            db.close()


    def update_permissions(
            self,
            *,
            document_id: int,
            tenant_id: str,
            visibility: str,
            departments: list[str] | None = None,
            roles: list[str] | None = None,
            user_ids: list[int] | None = None
    ) -> dict:

        """
        更新文档权限并同步 Milvus 元数据
        """

        departments = departments or []

        roles = roles or []

        user_ids = user_ids or []

        if visibility not in {"public", "restricted"}:

            raise ValueError(
                "visibility 仅支持 public / restricted"
            )

        db = SessionLocal()

        try:

            document = self.document_repository.get_by_id(
                db,
                document_id
            )

            if not document:

                raise ValueError(
                    "文档不存在"
                )

            if document.tenant_id != tenant_id:

                raise TenantAccessDenied(
                    "无权修改该文档权限"
                )

            # 1. 重建权限行
            self.permission_repository.delete_by_document(
                db,
                document_id
            )

            self.permission_repository.bulk_create(
                db,
                document_id=document_id,
                departments=departments,
                roles=roles,
                user_ids=user_ids,
                tenant_id=tenant_id,
            )

            # 2. 更新可见性
            self.document_repository.update_visibility(
                db,
                document_id,
                visibility,
            )

            # 3. 构建 access 并同步 Milvus
            rows = self.permission_repository.get_by_document(
                db,
                document_id
            )

            access = build_access_from_permission_rows(
                rows
            )

            synced = self.store.update_document_access(
                document_id,
                access,
            )

            return {
                "visibility": visibility,
                "departments": departments,
                "roles": roles,
                "user_ids": user_ids,
                "synced_chunks": synced,
            }

        finally:

            db.close()
