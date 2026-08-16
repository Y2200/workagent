from abc import ABC, abstractmethod


class BaseTool(ABC):

    """
    Agent 工具基类

    所有工具必须提供 name/description/input_schema/execute
    禁止工具直接访问数据库（统一经 Service）
    """

    name: str = ""

    description: str = ""

    input_schema: dict = {}

    # 权限声明（Enterprise Agent 统一规范，Phase 1）
    # - REQUIRED_PERMISSION: 整个工具统一权限码（如 notification_tool）
    # - PERMISSION_MAP: action → 权限码（如 task_tool/document_tool）
    REQUIRED_PERMISSION: str = ""

    PERMISSION_MAP: dict[str, str] = {}


    def check_permission(
            self,
            context,
            action: str | None = None
    ) -> str | None:

        """
        统一权限校验钩子

        返回缺失的权限码（None = 通过）。
        context 需含 permissions: set[str]（由 Runtime context_builder 注入）。
        """

        permissions = getattr(
            context,
            "permissions",
            set(),
        )

        if (
            self.REQUIRED_PERMISSION
            and self.REQUIRED_PERMISSION not in permissions
        ):

            return self.REQUIRED_PERMISSION

        if action:

            required = self.PERMISSION_MAP.get(
                action
            )

            if required and required not in permissions:

                return required

        return None


    @staticmethod
    def denied(code: str) -> dict:

        """
        标准权限拒绝结果
        """

        return {
            "error": "permission_denied",
            "message": f"无 {code} 权限",
        }


    @abstractmethod
    def execute(
            self,
            **kwargs
    ) -> dict:

        """
        执行工具，返回结构化结果
        """
