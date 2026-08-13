from datetime import datetime

from work_agent.agent.agents.base import BaseAgent
from work_agent.agent.agents.schemas import AgentResult
from work_agent.agent.schemas import IntentType
from work_agent.agent.tools.task_tool import TaskTool


def _format_deadline(
        deadline_iso: str | None
) -> str:
    """
    ISO 截止时间 → "8月20日"（便于企微阅读）
    """

    if not deadline_iso:

        return "未设置"

    try:

        dt = datetime.fromisoformat(deadline_iso)

        return f"{dt.month}月{dt.day}日"

    except (ValueError, TypeError):

        return deadline_iso or "未设置"


def _list_text(result: dict) -> str:

    tasks = result.get("tasks", [])

    if not tasks:

        return "你当前没有任务。"

    lines = [
        "你当前的任务：",
    ]

    for i, t in enumerate(tasks, 1):

        lines.append(
            f"{i}. {t['title']}  "
            f"进度 {t['progress']}%  截止 {_format_deadline(t['deadline'])}"
        )

    return "\n".join(lines)


def _confirmation_text(task: dict, parsed: dict) -> str:

    done = parsed.get("done") or []

    remaining = parsed.get("remaining") or []

    lines = [
        "我检测到你的提交：",
        "",
        f"任务：{task['title']}",
        f"当前进度：{parsed.get('progress', 0)}%",
    ]

    if done:

        lines.append("已完成：")

        lines.extend(f"- {item}" for item in done)

    if remaining:

        lines.append("剩余：")

        lines.extend(f"- {item}" for item in remaining)

    lines.append("")
    lines.append("确认提交吗？（回复「确认」或「取消」）")

    return "\n".join(lines)


class TaskAgent(BaseAgent):

    """
    任务督导 Agent

    通过 TaskTool 处理任务查询/进度提交/确认
    禁止直接访问 DB
    """

    name = "task_agent"

    description = "企业任务督导（查看任务/提交进度/确认）"

    handled_kinds = ["task"]


    def __init__(
            self,
            task_tool: TaskTool | None = None
    ):

        self.task_tool = task_tool or TaskTool()


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

        action = (
            (step.action or "list")
            if step
            else "list"
        )

        tool_result = self.task_tool.execute(
            context=context,
            action=action,
            query=message,
            content=message,
        )

        response = self._format_response(
            tool_result,
            action,
        )

        return AgentResult(
            agent=self.name,
            response=response,
            intent=IntentType.TASK_MANAGEMENT,
            knowledge_sources=[],
            permission_denied=(
                tool_result.get("error") == "permission_denied"
            ),
            token_usage=0,
            tools_called=["task_tool"],
            tool_calls=[
                {
                    "tool": "task_tool",
                    "action": action,
                }
            ],
        )


    def _format_response(
            self,
            result: dict,
            action: str
    ) -> str:

        # 权限拒绝 / 明确错误
        if result.get("error") == "permission_denied":

            return result.get("message", "无权操作")

        if result.get("status") == "error":

            return result.get("message", "操作失败")

        # 查看任务
        if action == "list":

            return _list_text(result)

        # 提交进度 → 待确认
        if action in ("submit", "complete"):

            if result.get("status") == "awaiting_confirmation":

                return _confirmation_text(
                    result["task"],
                    result["parsed"],
                )

            if result.get("status") in ("no_tasks", "task_not_found"):

                return result.get("message", "提交失败")

        # 确认
        if action == "confirm":

            if result.get("status") == "confirmed":

                parsed = result.get("parsed", {})

                task = result.get("task", {})

                return (
                    f"已确认：任务「{task.get('title', '')}」"
                    f"进度已更新为 {parsed.get('progress', 0)}%。"
                )

            if result.get("status") == "no_pending":

                return result.get("message", "没有待确认的提交")

        # 取消
        if action == "cancel":

            if result.get("status") == "cancelled":

                return "已取消本次提交。"

            if result.get("status") == "no_pending":

                return result.get("message", "没有待确认的提交")

        return "任务处理完成。"
