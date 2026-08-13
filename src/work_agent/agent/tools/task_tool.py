from work_agent.agent.context import AgentContext
from work_agent.agent.tools.base import BaseTool
from work_agent.core.exceptions import TenantAccessDenied


class TaskTool(BaseTool):

    """
    任务督导工具

    内部经 TaskService，禁止直接访问 DB
    """

    name = "task_tool"

    description = "任务督导（查看任务/提交进度/确认提交/完成任务）"

    input_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "submit", "confirm", "cancel", "complete"],
            },
            "query": {
                "type": "string",
            },
        },
    }

    # action → 所需权限码
    PERMISSION_MAP = {
        "list": "task:view",
        "detail": "task:view",
        "submit": "task:view",
        "complete": "task:view",
        "confirm": "task:view",
        "cancel": "task:view",
    }


    def execute(
            self,
            *,
            context: AgentContext,
            action: str,
            query: str = "",
            content: str = "",
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
        from work_agent.core.container import task_service

        try:

            return self._dispatch(
                task_service,
                action,
                context=context,
                query=query,
                content=content,
            )

        except TenantAccessDenied:

            return {
                "error": "permission_denied",
                "message": "无权操作该任务（跨租户）",
            }


    def _dispatch(
            self,
            task_service,
            action: str,
            *,
            context: AgentContext,
            query: str,
            content: str
    ) -> dict:

        # 查看任务
        if action == "list":

            tasks = task_service.list_employee_tasks(
                tenant_id=context.tenant_id,
                employee_id=context.user_id,
            )

            return {
                "action": "list",
                "tasks": [
                    {
                        "id": t.id,
                        "title": t.title,
                        "status": t.status,
                        "progress": t.progress,
                        "priority": t.priority,
                        "deadline": (
                            t.deadline.isoformat()
                            if t.deadline
                            else None
                        ),
                    }
                    for t in tasks
                ],
            }

        # 单个任务详情（任务上下文命中，如直接说任务名）
        if action == "detail":

            title = query or ""

            task = task_service.get_employee_task_by_title(
                tenant_id=context.tenant_id,
                employee_id=context.user_id,
                title=title,
            )

            if not task:

                return {
                    "status": "error",
                    "message": f"未找到任务「{title}」",
                }

            return {
                "action": "detail",
                "task": {
                    "id": task.id,
                    "title": task.title,
                    "status": task.status,
                    "progress": task.progress,
                    "priority": task.priority,
                    "description": task.description,
                    "deadline": (
                        task.deadline.isoformat()
                        if task.deadline
                        else None
                    ),
                },
            }

        # 提交进度（AI 解析 → 待确认）
        if action in ("submit", "complete"):

            result = task_service.submit_progress_feedback(
                tenant_id=context.tenant_id,
                employee_id=context.user_id,
                content=content or query,
                force_progress=(
                    100
                    if action == "complete"
                    else None
                ),
            )

            return result

        # 确认 / 取消
        if action == "confirm":

            return task_service.confirm_pending(
                tenant_id=context.tenant_id,
                employee_id=context.user_id,
            )

        if action == "cancel":

            return task_service.cancel_pending(
                tenant_id=context.tenant_id,
                employee_id=context.user_id,
            )

        return {
            "status": "error",
            "message": f"不支持的操作: {action}",
        }
