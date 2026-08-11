from work_agent.agent.tools.analysis_tool import AnalysisTool
from work_agent.agent.tools.audit_tool import AuditTool
from work_agent.agent.tools.document_tool import DocumentTool
from work_agent.agent.tools.knowledge_tool import KnowledgeTool
from work_agent.agent.tools.permission_tool import PermissionTool


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
            ]
        ):

            self.register(tool)


    def register(self, tool) -> None:

        self._tools[tool.name] = tool


    def get(self, name: str):

        return self._tools.get(name)


    def list_tools(self) -> list[dict]:

        return [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.input_schema,
            }
            for tool in self._tools.values()
        ]


# 全局单例
tool_registry = ToolRegistry()
