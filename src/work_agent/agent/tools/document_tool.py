from work_agent.agent.context import AgentContext
from work_agent.agent.tools.base import BaseTool
from work_agent.core.exceptions import TenantAccessDenied


class DocumentTool(BaseTool):

    """
    文档操作工具

    内部经 DocumentService，禁止直接访问 DB
    """

    name = "document_tool"

    description = "知识库文档操作（列出/查看/删除/上传）"

    input_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "get", "delete", "upload"],
            },
            "document_id": {
                "type": "integer",
            },
            "filename": {
                "type": "string",
            },
            "content": {
                "type": "string",
            },
            "category": {
                "type": "string",
            },
        },
    }

    # action → 所需权限码
    PERMISSION_MAP = {
        "list": "document:view",
        "get": "document:view",
        "delete": "document:delete",
        "upload": "document:create",
    }


    def execute(
            self,
            *,
            context: AgentContext,
            action: str,
            document_id: int | None = None,
            filename: str | None = None,
            content: str | None = None,
            category: str = "",
            **kwargs
    ) -> dict:

        required = self.PERMISSION_MAP.get(
            action
        )

        if required and required not in context.permissions:

            return {
                "error": "permission_denied",
                "message": f"无 {required} 权限",
            }

        # 延迟导入，避免循环依赖
        from work_agent.core.container import document_service

        try:

            return self._dispatch(
                document_service,
                action,
                context=context,
                document_id=document_id,
                filename=filename,
                content=content,
                category=category,
            )

        except TenantAccessDenied:

            return {
                "error": "permission_denied",
                "message": "无权操作该文档（跨租户）",
            }


    def _dispatch(
            self,
            document_service,
            action: str,
            *,
            context: AgentContext,
            document_id,
            filename,
            content,
            category
    ) -> dict:

        if action == "list":

            documents = document_service.list_documents(
                tenant_id=context.tenant_id,
            )

            return {
                "documents": [
                    {
                        "id": doc.id,
                        "filename": doc.filename,
                        "category": doc.category,
                        "status": doc.status,
                        "visibility": doc.visibility,
                    }
                    for doc in documents
                ],
            }

        if action == "get":

            document = document_service.get_document(
                document_id,
                tenant_id=context.tenant_id,
            )

            if not document:
                return {"error": "not_found"}

            return {
                "document": {
                    "id": document.id,
                    "filename": document.filename,
                    "category": document.category,
                    "status": document.status,
                    "visibility": document.visibility,
                },
            }

        if action == "delete":

            deleted = document_service.delete(
                document_id,
                tenant_id=context.tenant_id,
            )

            return {
                "deleted": deleted,
                "document_id": document_id,
            }

        if action == "upload":

            document = document_service.upload(
                filename=filename or "unnamed",
                data=(content or "").encode("utf-8"),
                category=category,
                uploader=context.username or "system",
                tenant_id=context.tenant_id,
            )

            return {
                "document_id": document.id,
                "status": document.status,
            }

        return {
            "error": "unknown_action",
            "message": f"不支持的操作: {action}",
        }
