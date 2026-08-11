from work_agent.agent.context import AgentContext
from work_agent.agent.tools.base import BaseTool


class AuditTool(BaseTool):

    """
    审计查询工具

    内部经 AuditService，禁止直接访问 DB
    """

    name = "audit_tool"

    description = "查询问答审计与操作审计日志"

    input_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["logs", "operations", "statistics"],
            },
            "page": {
                "type": "integer",
            },
            "page_size": {
                "type": "integer",
            },
        },
    }

    REQUIRED_PERMISSION = "audit:view"


    def execute(
            self,
            *,
            context: AgentContext,
            action: str,
            page: int = 1,
            page_size: int = 20,
            **kwargs
    ) -> dict:

        if self.REQUIRED_PERMISSION not in context.permissions:

            return {
                "error": "permission_denied",
                "message": f"无 {self.REQUIRED_PERMISSION} 权限",
            }

        # 延迟导入，避免循环依赖
        from work_agent.core.container import audit_service

        if action == "logs":

            page_data = audit_service.list_logs(
                tenant_id=context.tenant_id,
                page=page,
                page_size=page_size,
            )

            return {
                "total": page_data["total"],
                "items": [
                    {
                        "id": item.id,
                        "user_id": item.user_id,
                        "username": getattr(item, "username", None),
                        "question": item.question,
                        "status": item.status,
                        "latency_ms": item.latency_ms,
                        "created_at": (
                            item.created_at.isoformat()
                            if item.created_at
                            else None
                        ),
                    }
                    for item in page_data["items"]
                ],
            }

        if action == "operations":

            page_data = audit_service.list_operations(
                tenant_id=context.tenant_id,
                page=page,
                page_size=page_size,
            )

            return {
                "total": page_data["total"],
                "items": [
                    {
                        "id": item.id,
                        "user_id": item.user_id,
                        "username": getattr(item, "username", None),
                        "action": item.action,
                        "target_type": item.target_type,
                        "created_at": (
                            item.created_at.isoformat()
                            if item.created_at
                            else None
                        ),
                    }
                    for item in page_data["items"]
                ],
            }

        if action == "statistics":

            return audit_service.get_statistics(
                tenant_id=context.tenant_id,
            )

        return {
            "error": "unknown_action",
            "message": f"不支持的操作: {action}",
        }
