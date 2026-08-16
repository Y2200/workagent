from work_agent.agent.tools.analysis_tool import AnalysisTool
from work_agent.agent.tools.audit_tool import AuditTool
from work_agent.agent.tools.document_tool import DocumentTool
from work_agent.agent.tools.knowledge_tool import KnowledgeTool
from work_agent.agent.tools.permission_tool import PermissionTool
from work_agent.agent.tools.task_tool import TaskTool
from work_agent.agent.tools.user_tool import UserTool


class ToolRegistry:

    """
    工具注册表
    """

    def __init__(
            self,
            tools: list | None = None
    ):

        self._tools: dict[str, object] = {}

        for tool in (
            tools
            or [
                KnowledgeTool(),
                DocumentTool(),
                PermissionTool(),
                AuditTool(),
                AnalysisTool(),
                TaskTool(),
                UserTool(),
            ]
        ):

            self.register(tool)


    def register(self, tool) -> None:

        self._tools[tool.name] = tool


    def get(self, name: str):

        return self._tools.get(name)


    def list_tools(self) -> list[dict]:

        """
        统一工具清单（Enterprise Agent）

        含权限信息：required_permission（整工具）/ permission_map（action → 权限码），
        供 planner/LLM 编排与审计使用。
        """

        return [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.input_schema,
                "required_permission": getattr(
                    tool,
                    "REQUIRED_PERMISSION",
                    "",
                ),
                "permission_map": dict(
                    getattr(
                        tool,
                        "PERMISSION_MAP",
                        {},
                    )
                ),
            }
            for tool in self._tools.values()
        ]


# 全局单例
tool_registry = ToolRegistry()
