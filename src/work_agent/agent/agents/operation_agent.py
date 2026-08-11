import json

from work_agent.agent.agents.base import BaseAgent
from work_agent.agent.agents.schemas import AgentResult
from work_agent.agent.tools.registry import tool_registry


class OperationAgent(BaseAgent):

    """
    文档/权限操作 Agent

    按计划步骤执行对应工具（document_tool / permission_tool）
    禁止直接访问 DB
    """

    name = "operation_agent"

    description = "文档与权限操作"

    handled_kinds = ["document"]


    def run(
            self,
            *,
            context,
            plan,
            message: str
    ) -> AgentResult:

        step = (
            plan.steps[0]
            if plan and plan.steps
            else None
        )

        if not step:

            return AgentResult(
                agent=self.name,
                response="暂不支持该操作，请联系管理员在后台处理。",
                intent=plan.intent if plan else "",
                permission_denied=False,
            )

        tool = tool_registry.get(
            step.tool
        )

        if not tool:

            return AgentResult(
                agent=self.name,
                response=f"工具 {step.tool} 不可用。",
                intent=plan.intent if plan else "",
                permission_denied=False,
                tools_called=[step.tool],
                tool_calls=[{"tool": step.tool, "action": step.action}],
            )

        tool_result = tool.execute(
            context=context,
            action=step.action,
            **step.args,
        )

        denied = (
            tool_result.get("error")
            == "permission_denied"
        )

        response = self._format_result(
            tool.name,
            step.action,
            tool_result,
        )

        return AgentResult(
            agent=self.name,
            response=response,
            intent=plan.intent if plan else "",
            permission_denied=denied,
            tools_called=[step.tool],
            tool_calls=[{"tool": step.tool, "action": step.action}],
        )


    def _format_result(
            self,
            tool_name: str,
            action: str | None,
            result: dict
    ) -> str:

        if result.get("error") == "permission_denied":

            return f"权限不足：{result.get('message', '无权操作')}"

        if result.get("error") == "not_found":

            return "未找到对应文档。"

        if tool_name == "document_tool":

            if action == "list":

                documents = result.get("documents", [])

                if not documents:
                    return "当前知识库暂无文档。"

                lines = [
                    f"{i + 1}. {doc['filename']} "
                    f"（{doc.get('category', '')}，{doc.get('status', '')}）"
                    for i, doc in enumerate(documents)
                ]

                return "当前知识库文档：\n" + "\n".join(lines)

            if action == "delete":

                if result.get("deleted"):
                    return f"文档 {result.get('document_id')} 已删除。"

                return f"文档 {result.get('document_id')} 不存在。"

            if action == "upload":

                return (
                    f"文档已上传（id={result.get('document_id')}），"
                    f"正在异步处理，状态：{result.get('status')}"
                )

            if action == "get":

                doc = result.get("document", {})

                if doc:
                    return (
                        f"文档：{doc.get('filename')}，"
                        f"分类：{doc.get('category', '')}，"
                        f"状态：{doc.get('status', '')}"
                    )

        if tool_name == "permission_tool":

            permissions = result.get("permissions", {})

            return (
                f"权限已更新（可见性：{permissions.get('visibility', '')}，"
                f"部门：{permissions.get('departments', [])}，"
                f"角色：{permissions.get('roles', [])}）"
            )

        return json.dumps(
            result,
            ensure_ascii=False,
        )
