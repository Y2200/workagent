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
                "enum": [
                    "list",
                    "detail",
                    "submit",
                    "submit_all",
                    "confirm",
                    "cancel",
                    "complete",
                    "department_tasks",
                    "create",
                ],
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
        "submit_all": "task:view",
        "complete": "task:view",
        "confirm": "task:view",
        "cancel": "task:view",
        "department_tasks": "task:view",
        "create": "task:create",
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
                **kwargs,
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
            content: str,
            **kwargs
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

        # 按部门查任务清单（部门管理员/管理员）
        if action == "department_tasks":

            from work_agent.agent.tools.permissions import check_department_scope

            # 部门作用域：DEPARTMENT_ADMIN 强制本部门；管理员可指定
            target_department = (
                kwargs.get("department")
                or context.department
                or ""
            )

            if not check_department_scope(
                    context,
                    target_department,
            ):

                return {
                    "error": "permission_denied",
                    "message": "只能查看本部门任务",
                }

            tasks = task_service.list_tasks_by_department(
                tenant_id=(
                    context.tenant_id
                    if context.tenant_id
                    else None
                ),
                department=target_department,
            )

            # 富化执行人姓名（复用 user 查询，避免 Agent 直连 DB）
            employee_names = self._employee_names(tasks)

            return {
                "action": "department_tasks",
                "department": target_department,
                "tasks": [
                    {
                        "id": t.id,
                        "title": t.title,
                        "status": t.status,
                        "progress": t.progress,
                        "priority": t.priority,
                        "employee": employee_names.get(
                            t.employee_id,
                            str(t.employee_id),
                        ),
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

        # 批量提交全部未完成任务
        if action == "submit_all":

            return task_service.submit_all_progress(
                tenant_id=context.tenant_id,
                employee_id=context.user_id,
                content=content or query,
            )

        # 任务发布：解析 → 待确认草稿（不落正式表）
        if action == "create":

            return task_service.preview_create_task(
                creator_id=context.user_id,
                creator_tenant_id=context.tenant_id,
                content=content or query,
            )

        # 确认 / 取消：优先消解任务创建草稿，其次进度确认
        if action == "confirm":

            created = task_service.confirm_pending_create(
                creator_id=context.user_id,
            )

            if created:

                return created

            return task_service.confirm_pending(
                tenant_id=context.tenant_id,
                employee_id=context.user_id,
            )

        if action == "cancel":

            cancelled = task_service.cancel_pending_create(
                creator_id=context.user_id,
            )

            if cancelled:

                return cancelled

            return task_service.cancel_pending(
                tenant_id=context.tenant_id,
                employee_id=context.user_id,
            )

        return {
            "status": "error",
            "message": f"不支持的操作: {action}",
        }


    @staticmethod
    def _employee_names(tasks) -> dict[int, str]:

        """
        批量解析任务执行人姓名（部门任务清单富化）

        经 UserRepository，避免 Agent 直连 DB（分层铁律）
        """

        if not tasks:
            return {}

        from work_agent.core.container import user_service

        employee_ids = {
            t.employee_id
            for t in tasks
        }

        names = {}

        for uid in employee_ids:

            user = user_service.get_by_id(
                uid,
            )

            if user:

                names[uid] = (
                    user.real_name
                    or user.username
                    or str(uid)
                )

        return names
