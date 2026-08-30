from work_agent.agent.context import AgentContext
from work_agent.agent.tools.base import BaseTool


class UserTool(BaseTool):

    """
    用户查询工具（Enterprise Agent）

    - resolve: 按姓名/账号解析员工（DB 确定性查询，LLM 不负责）
    - list_department: 列出部门成员

    内部经 UserRepository，禁止直接访问 DB（遵循分层铁律）。
    被 task_tool.create / notification_tool 复用。
    """

    name = "user_tool"

    description = "查询用户（按姓名/账号解析员工、列出部门成员）"

    input_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["resolve", "list_department"],
            },
            "name": {
                "type": "string",
            },
            "department": {
                "type": "string",
            },
        },
        "required": ["action"],
    }

    # action → 权限码
    PERMISSION_MAP = {
        "resolve": "task:view",
        "list_department": "task:view",
    }


    def execute(
            self,
            *,
            context: AgentContext,
            action: str,
            name: str = "",
            department: str = "",
            **kwargs
    ) -> dict:

        required = self.check_permission(
            context,
            action,
        )

        if required:

            return self.denied(required)

        # 经 Service 访问用户数据（分层铁律：Tool 禁直连 DB）
        from work_agent.core.container import user_service

        if action == "resolve":

            return self._resolve(
                user_service,
                context,
                name,
            )

        if action == "list_department":

            return self._list_department(
                user_service,
                context,
                department,
            )

        return {
            "error": "unknown_action",
            "message": f"不支持的操作: {action}",
        }


    def _resolve(
            self,
            user_service,
            context: AgentContext,
            name: str
    ) -> dict:

        """
        按姓名/账号解析员工（经 user_service）

        多租户铁律：租户管理员/部门管理员按本租户过滤；
        SUPER_ADMIN（tenant_id 空）平台全量。
        """

        if not name:

            return {
                "status": "error",
                "message": "请提供员工姓名或账号",
            }

        users = user_service.search_by_name(
            keyword=name,
            tenant_id=(
                context.tenant_id
                if context.tenant_id
                else ""
            ),
        )

        if not users:

            return {
                "status": "not_found",
                "message": f"未找到员工「{name}」",
            }

        return {
            "status": "found",
            "users": [
                self._user_dict(u)
                for u in users
            ],
        }


    def _list_department(
            self,
            user_service,
            context: AgentContext,
            department: str
    ) -> dict:

        """
        列出部门成员（经 user_service）

        权限要求（仅部门经理及以上，不可跨部门）：
        - 角色门：仅 SUPER_ADMIN / TENANT_ADMIN / DEPARTMENT_ADMIN
        - 部门作用域：DEPARTMENT_ADMIN 强制本部门（permissions.py 校验）
        """

        from work_agent.agent.tools.permissions import check_department_scope

        # 角色门：普通员工（USER）不可查看部门员工名单
        role_codes = getattr(
            context,
            "role_codes",
            set(),
        )

        if not (
            role_codes
            & {"SUPER_ADMIN", "TENANT_ADMIN", "DEPARTMENT_ADMIN"}
        ):

            return {
                "error": "permission_denied",
                "message": "仅部门经理可查看本部门员工",
            }

        target = department or context.department

        if not check_department_scope(
                context,
                target,
        ):

            return {
                "error": "permission_denied",
                "message": "只能查看本部门成员",
            }

        users = user_service.list_by_department(
            department=target,
            tenant_id=(
                context.tenant_id
                if context.tenant_id
                else ""
            ),
        )

        return {
            "status": "found",
            "department": target,
            "users": [
                self._user_dict(u)
                for u in users
            ],
        }


    @staticmethod
    def _user_dict(user) -> dict:

        return {
            "id": user.id,
            "username": user.username,
            "real_name": user.real_name or user.username,
            "department": user.department or "",
            "role": user.role or "",
            "email": user.email or "",
            "wechat_user_id": user.wechat_user_id or "",
            "tenant_id": user.tenant_id,
        }
