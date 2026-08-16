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


STATUS_NAMES = {
    "pending": "待处理",
    "processing": "进行中",
    "completed": "已完成",
    "overdue": "已逾期",
}


def _detail_text(task: dict) -> str:

    return (
        f"任务：{task['title']}\n"
        f"进度：{task['progress']}%\n"
        f"状态：{STATUS_NAMES.get(task['status'], task['status'])}\n"
        f"截止：{_format_deadline(task.get('deadline'))}\n"
        f"优先级：{task.get('priority', 'normal')}"
    )


def _batch_confirmation_text(result: dict) -> str:

    tasks = result.get("tasks", [])

    progress = result.get("progress", 0)

    lines = [
        "检测到您准备更新全部任务：",
    ]

    lines.extend(
        f"- {t['title']}：{progress}%"
        for t in tasks
    )

    lines.append("")
    lines.append("确认提交吗？（回复「确认」或「取消」）")

    return "\n".join(lines)


def _confirmed_text(result: dict) -> str:

    items = result.get("items", [])

    if len(items) == 1:

        item = items[0]

        return (
            f"已确认：任务「{item['task']['title']}」"
            f"进度已更新为 {item['progress']}%。"
        )

    lines = [
        f"已确认 {len(items)} 个任务：",
    ]

    lines.extend(
        f"- {item['task']['title']}：{item['progress']}%"
        for item in items
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


def _department_tasks_text(result: dict) -> str:

    department = result.get("department", "")

    tasks = result.get("tasks", [])

    if not tasks:

        return f"{department or '该部门'}暂无任务。"

    lines = [
        f"{department or '本部门'}任务情况：",
    ]

    # 按执行人分组汇总
    by_employee: dict[str, list] = {}

    for t in tasks:

        emp = t.get("employee") or str(t.get("id"))

        by_employee.setdefault(emp, []).append(t)

    for emp, emp_tasks in by_employee.items():

        completed = sum(
            1
            for t in emp_tasks
            if t["status"] == "completed"
        )

        active = len(emp_tasks) - completed

        risky = sum(
            1
            for t in emp_tasks
            if t["status"] in ("pending", "processing")
            and (
                t.get("priority") == "high"
                or t.get("deadline") is not None
            )
        )

        lines.append(
            f"{emp}：共{len(emp_tasks)}个 完成{completed} "
            f"进行中{active} 风险{risky}"
        )

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

        # 任务发布（解析 → 待确认）
        if action == "create":

            if result.get("status") == "awaiting_confirmation":

                return result.get(
                    "message",
                    "已生成任务草稿，请确认。",
                )

            if result.get("status") == "need_info":

                return result.get(
                    "message",
                    "请提供任务名称和执行人。",
                )

            if result.get("status") == "employee_not_found":

                return result.get(
                    "message",
                    "未找到执行人。",
                )

            return result.get("message", "任务发布处理完成")

        # 按部门查任务
        if action == "department_tasks":

            return _department_tasks_text(result)

        # 查看任务
        if action == "list":

            return _list_text(result)

        # 单个任务详情
        if action == "detail":

            if result.get("status") == "error":

                return result.get("message", "未找到任务")

            if result.get("task"):

                return _detail_text(result["task"])

        # 提交进度 → 待确认
        if action in ("submit", "complete"):

            if result.get("status") == "awaiting_confirmation":

                return _confirmation_text(
                    result["task"],
                    result["parsed"],
                )

            if result.get("status") in ("no_tasks", "task_not_found"):

                return result.get("message", "提交失败")

        # 批量提交 → 待确认
        if action == "submit_all":

            if result.get("status") == "awaiting_confirmation":

                return _batch_confirmation_text(result)

            if result.get("status") == "no_tasks":

                return result.get("message", "没有进行中的任务")

        # 确认
        if action == "confirm":

            # 任务创建确认完成
            if result.get("status") == "task_created":

                return result.get("message", "任务已创建。")

            if result.get("status") == "confirmed":

                return _confirmed_text(result)

            if result.get("status") == "no_pending":

                return result.get("message", "没有待确认的提交")

        # 取消
        if action == "cancel":

            if result.get("status") == "cancelled_create":

                return result.get("message", "已取消任务创建。")

            if result.get("status") == "cancelled":

                return "已取消本次提交。"

            if result.get("status") == "no_pending":

                return result.get("message", "没有待确认的提交")

        return "任务处理完成。"
