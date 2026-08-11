from work_agent.agent.context import AgentContext
from work_agent.agent.tools.base import BaseTool
from work_agent.core.exceptions import TenantAccessDenied


class PermissionTool(BaseTool):

    """
    权限管理工具

    内部经 PermissionService，禁止直接访问 DB / Milvus
    """

    name = "permission_tool"

    description = "文档权限管理（查看/修改可见部门、角色、指定用户）"

    input_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["get", "update"],
            },
            "document_id": {
                "type": "integer",
            },
            "visibility": {
                "type": "string",
                "enum": ["public", "restricted"],
            },
            "departments": {
                "type": "array",
                "items": {"type": "string"},
            },
            "roles": {
                "type": "array",
                "items": {"type": "string"},
            },
            "user_ids": {
                "type": "array",
                "items": {"type": "integer"},
            },
        },
    }

    REQUIRED_PERMISSION = "document:permission_manage"


    def execute(
            self,
            *,
            context: AgentContext,
            action: str,
            document_id: int,
            visibility: str = "public",
            departments: list[str] | None = None,
            roles: list[str] | None = None,
            user_ids: list[int] | None = None,
            **kwargs
    ) -> dict:

        if self.REQUIRED_PERMISSION not in context.permissions:

            return {
                "error": "permission_denied",
                "message": f"无 {self.REQUIRED_PERMISSION} 权限",
            }

        # 延迟导入，避免循环依赖
        from work_agent.core.container import permission_service

        try:

            return self._dispatch(
                permission_service,
                action,
                context=context,
                document_id=document_id,
                visibility=visibility,
                departments=departments,
                roles=roles,
                user_ids=user_ids,
            )

        except TenantAccessDenied:

            return {
                "error": "permission_denied",
                "message": "无权操作该文档权限（跨租户）",
            }

        except ValueError as exc:

            return {
                "error": "not_found",
                "message": str(exc),
            }


    def _dispatch(
            self,
            permission_service,
            action: str,
            *,
            context: AgentContext,
            document_id,
            visibility,
            departments,
            roles,
            user_ids
    ) -> dict:

        if action == "get":

            result = permission_service.get_permissions(
                document_id,
                tenant_id=context.tenant_id,
            )

            if result is None:
                return {"error": "not_found"}

            return {"permissions": result}

        if action == "update":

            result = permission_service.update_permissions(
                document_id=document_id,
                tenant_id=context.tenant_id,
                visibility=visibility,
                departments=departments or [],
                roles=roles or [],
                user_ids=user_ids or [],
            )

            return {"permissions": result}

        return {
            "error": "unknown_action",
            "message": f"不支持的操作: {action}",
        }
