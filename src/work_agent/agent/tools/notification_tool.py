from work_agent.agent.context import AgentContext
from work_agent.agent.tools.base import BaseTool


class NotificationTool(BaseTool):

    """
    主动通知/督促工具（Enterprise Agent）

    - send_wechat: 企微定向提醒员工
    - send_email:  邮件定向提醒（外部通信，confirmation_required=true；
                   SMTP 未启用时明确提示，不走失败流程）

    权限：task:notify（新权限码，DEPARTMENT_ADMIN 及以上）
    部门作用域：DEPARTMENT_ADMIN 仅能提醒本部门员工
    内部经 notification_service / user_service，禁止直连 DB
    """

    name = "notification_tool"

    description = "主动通知/督促（企微/邮件定向提醒员工）"

    input_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["send_wechat", "send_email"],
            },
            "employee_id": {
                "type": "integer",
            },
            "content": {
                "type": "string",
            },
            "subject": {
                "type": "string",
            },
            "task_id": {
                "type": "integer",
            },
        },
        "required": ["action", "employee_id", "content"],
    }

    REQUIRED_PERMISSION = "task:notify"


    def execute(
            self,
            *,
            context: AgentContext,
            action: str,
            employee_id: int | None = None,
            content: str = "",
            subject: str = "",
            task_id: int | None = None,
            **kwargs
    ) -> dict:

        required = self.check_permission(
            context,
            action,
        )

        if required:

            return self.denied(required)

        if not employee_id:

            return {
                "error": "missing_employee",
                "message": "请指定目标员工（先经 user_tool 解析）",
            }

        if not content or not content.strip():

            return {
                "error": "missing_content",
                "message": "请提供提醒内容",
            }

        # 经 service 访问用户（分层铁律）
        from work_agent.core.container import user_service

        target = user_service.get_by_id(
            employee_id,
        )

        if not target:

            return {
                "error": "employee_not_found",
                "message": f"未找到员工 id={employee_id}",
            }

        # 部门作用域：DEPARTMENT_ADMIN 仅提醒本部门
        from work_agent.agent.tools.permissions import check_department_scope

        if not check_department_scope(
                context,
                target.department or "",
        ):

            return {
                "error": "permission_denied",
                "message": "只能提醒本部门员工",
            }

        from work_agent.core.container import notification_service

        if action == "send_wechat":

            return self._send_wechat(
                notification_service,
                context,
                target,
                content,
                task_id,
            )

        if action == "send_email":

            return self._send_email(
                notification_service,
                context,
                target,
                subject,
                content,
                task_id,
            )

        return {
            "error": "unknown_action",
            "message": f"不支持的操作: {action}",
        }


    @staticmethod
    def _send_wechat(
            notification_service,
            context: AgentContext,
            target,
            content: str,
            task_id: int | None
    ) -> dict:

        if not target.wechat_user_id:

            return {
                "error": "no_wechat_binding",
                "message": (
                    f"员工「{target.real_name or target.username}」"
                    "未绑定企业微信，无法发送企微提醒"
                ),
            }

        return notification_service.send_wechat(
            tenant_id=target.tenant_id,
            task_id=task_id or 0,
            receiver_id=target.id,
            wechat_user_id=target.wechat_user_id,
            content=content,
        )


    @staticmethod
    def _send_email(
            notification_service,
            context: AgentContext,
            target,
            subject: str,
            content: str,
            task_id: int | None
    ) -> dict:

        if not target.email:

            return {
                "error": "no_email",
                "message": (
                    f"员工「{target.real_name or target.username}」"
                    "未配置邮箱，无法发送邮件"
                ),
            }

        return notification_service.send_email(
            tenant_id=target.tenant_id,
            task_id=task_id or 0,
            receiver_id=target.id,
            to=target.email,
            subject=subject or "任务提醒",
            content=content,
        )
