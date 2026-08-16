import json
import re

from work_agent.agent.context import AgentContext
from work_agent.agent.llm import get_llm
from work_agent.agent.schemas import IntentType, PlanResult, PlanStep
from work_agent.agent.tools.registry import tool_registry
from work_agent.agent.tools.selector import tool_selector
from work_agent.core.prompt_manager import prompt_manager
from work_agent.core.utils import is_greeting, parse_json


class AgentPlanner:

    """
    任务规划器

    根据意图 + 实体 + 上下文生成执行计划（PlanResult）

    - 确定性路径：已知意图快速规划（可靠、低延迟）
    - LLM 路径：复杂任务分解（workflow_planner prompt），失败回退确定性
    """

    def __init__(
            self,
            llm=None,
            selector=None,
            config_service=None
    ):

        self.llm = llm or get_llm()

        self.selector = selector or tool_selector

        self.config_service = config_service

        self.last_prompt_version = ""


    def _top_k(self, context) -> int:

        """
        从配置中心读取知识检索 top_k（缺省 5）
        """

        config_service = self._get_config_service()

        if config_service:

            value = config_service.get(
                "agent.default_top_k",
                context.tenant_id,
            )

            if isinstance(value, int) and value > 0:
                return value

        return 5


    def _get_config_service(self):

        if self.config_service is None:

            # 延迟导入，避免容器初始化循环依赖
            from work_agent.core.container import agent_config_service

            self.config_service = agent_config_service

        return self.config_service


    def plan(
            self,
            *,
            message: str,
            intent_result,
            context: AgentContext
    ) -> PlanResult:

        """
        生成执行计划
        """

        intent = intent_result.intent

        # ======================
        # 任务状态/进度消息统一归 task
        # （LLM 可能在 workflow_request / task 意图间摇摆，此处确定性归一）
        # ======================

        if (
            intent == IntentType.WORKFLOW_REQUEST
            and ("任务" in message or "进度" in message)
        ):

            intent = IntentType.QUERY_MY_TASK

        # ======================
        # 确定性路径
        # ======================

        if intent == IntentType.KNOWLEDGE_QUERY:

            return PlanResult(
                kind="knowledge",
                intent=intent,
                steps=[
                    PlanStep(
                        step_id=1,
                        tool="knowledge_tool",
                        action="search",
                        args={"top_k": self._top_k(context)},
                        description="检索企业知识库",
                    ),
                ],
                reasoning="知识查询：检索知识库并生成回答",
            )

        if intent == IntentType.DOCUMENT_OPERATION:

            selection = self.selector.select(
                intent=intent,
                entities=intent_result.entities,
                message=message,
                context=context,
            )

            if selection.get("tool"):

                args = dict(
                    selection.get(
                        "args",
                        {},
                    )
                    or {}
                )

                # action 由工具 executor 单独传参，避免重复
                args.pop("action", None)

                return PlanResult(
                    kind="document",
                    intent=intent,
                    steps=[
                        PlanStep(
                            step_id=1,
                            tool=selection["tool"],
                            action=selection.get("action", ""),
                            args=args,
                            description="文档/权限操作",
                        ),
                    ],
                    reasoning="文档操作：调用对应工具",
                )

        if intent == IntentType.AUDIT_QUERY:

            return PlanResult(
                kind="document",
                intent=intent,
                steps=[
                    PlanStep(
                        step_id=1,
                        tool="audit_tool",
                        action="logs",
                        args={"page_size": 5},
                        description="查询审计日志",
                    ),
                ],
                reasoning="审计查询：调用审计工具",
            )

        if intent == IntentType.RISK_ANALYSIS:

            return PlanResult(
                kind="risk",
                intent=intent,
                steps=[
                    PlanStep(
                        step_id=1,
                        tool="analysis_tool",
                        action="analyze",
                        args={"top_k": self._top_k(context)},
                        description="风险/任务分析",
                    ),
                ],
                reasoning="风险分析：检索制度并评估风险",
            )

        # 员工查自己的任务（query_my_task）
        if intent in (
            IntentType.QUERY_MY_TASK,
            IntentType.TASK_MANAGEMENT,  # 兼容别名
        ):

            action = (
                intent_result.entities.get("action")
                or ""
            )

            if action not in ("list", "detail"):

                action = _infer_query_action(message)

            return PlanResult(
                kind="task",
                intent=IntentType.QUERY_MY_TASK,
                steps=[
                    PlanStep(
                        step_id=1,
                        tool="task_tool",
                        action=action,
                        description="查询我的任务",
                    ),
                ],
                reasoning=f"查询我的任务：执行 {action}",
            )

        # 经理查员工/部门任务（query_employee_task）
        if intent == IntentType.QUERY_EMPLOYEE_TASK:

            action = (
                intent_result.entities.get("action")
                or "employee_tasks"
            )

            return PlanResult(
                kind="task",
                intent=intent,
                steps=[
                    PlanStep(
                        step_id=1,
                        tool="task_tool",
                        action=action,
                        description="查询员工/部门任务",
                    ),
                ],
                reasoning=f"查询员工/部门任务：执行 {action}",
            )

        # 员工提交/确认/取消/完成进度（submit_task）
        if intent == IntentType.SUBMIT_TASK:

            action = (
                intent_result.entities.get("action")
                or ""
            )

            if action not in (
                "submit",
                "submit_all",
                "confirm",
                "cancel",
                "complete",
            ):

                action = _infer_submit_action(message)

            # 批量语义确定性强覆盖
            if (
                "全部任务" in message
                or "所有任务" in message
            ):

                action = "submit_all"

            return PlanResult(
                kind="task",
                intent=IntentType.SUBMIT_TASK,
                steps=[
                    PlanStep(
                        step_id=1,
                        tool="task_tool",
                        action=action,
                        description="提交/确认任务进度",
                    ),
                ],
                reasoning=f"提交任务进度：执行 {action}",
            )

        # 经理发布任务（create_task，带确认）：解析 → 待确认草稿
        if intent == IntentType.CREATE_TASK:

            # 结构化 command（替代自由文本）：
            # {"intent": "create_task", "command": {"type": "task.create",
            #  "assignee_name": "...", "title": "...", "deadline": "..."}}
            command = {
                "intent": IntentType.CREATE_TASK,
                "command": {
                    "type": "task.create",
                    "assignee_name": (
                        intent_result.entities.get("employee_name")
                        or ""
                    ),
                    "title": (
                        intent_result.entities.get("title")
                        or ""
                    ),
                    "deadline": (
                        intent_result.entities.get("deadline_text")
                        or ""
                    ),
                },
            }

            return PlanResult(
                kind="task",
                intent=IntentType.CREATE_TASK,
                steps=[
                    PlanStep(
                        step_id=1,
                        tool="task_tool",
                        action="create",
                        args={"command": command},
                        description="任务发布（解析 → 确认 → 创建）",
                        confirmation_required=True,
                    ),
                ],
                reasoning="任务发布：解析并生成待确认草稿",
            )

        # 经理提醒/督促员工（remind_task；发邮件需确认）
        if intent == IntentType.REMIND_TASK:

            remind_action = (
                intent_result.entities.get("action")
                or "send_wechat"
            )

            return PlanResult(
                kind="task",
                intent=intent,
                steps=[
                    PlanStep(
                        step_id=1,
                        tool="notification_tool",
                        action=remind_action,
                        description="主动提醒/督促员工",
                        confirmation_required=(
                            remind_action == "send_email"
                        ),
                    ),
                ],
                reasoning="主动提醒：定向通知员工",
            )

        # 任务汇总/部门周报（summary_task）
        if intent == IntentType.SUMMARY_TASK:

            return PlanResult(
                kind="task",
                intent=intent,
                steps=[
                    PlanStep(
                        step_id=1,
                        tool="task_tool",
                        action="summary",
                        description="部门任务汇总",
                    ),
                ],
                reasoning="任务汇总：生成部门任务总结",
            )

        # 闲聊/问候：直接友好回复，不进 legacy 督导流
        if (
            intent == IntentType.SMALL_TALK
            or is_greeting(message)
        ):

            return PlanResult(
                kind="chat",
                intent=intent,
                steps=[],
                reasoning="闲聊/问候：直接友好回复",
            )

        # 其他（督导/未知）
        return PlanResult(
            kind="legacy",
            intent=intent,
            steps=[],
            reasoning="督导/未知路径：委托旧工作流",
        )


    def plan_with_llm(
            self,
            *,
            message: str,
            intent_result,
            context: AgentContext
    ) -> PlanResult:

        """
        LLM 复杂任务规划（多步分解），失败回退确定性
        """

        try:

            loaded = prompt_manager.load(
                "workflow_planner"
            )

            self.last_prompt_version = loaded["version"]

            prompt = loaded["content"].format(
                message=message,
                intent=intent_result.intent,
                entities=json.dumps(
                    intent_result.entities,
                    ensure_ascii=False,
                ),
                available_tools=json.dumps(
                    tool_registry.list_tools(),
                    ensure_ascii=False,
                ),
            )

            result = self.llm.invoke(
                prompt
            )

            data = parse_json(
                result.content
            )

            kind = data.get("kind", "")

            steps = [
                PlanStep(
                    step_id=int(step.get("step_id", i + 1)),
                    tool=step.get("tool", ""),
                    action=step.get("action", ""),
                    args=step.get("args", {}) or {},
                    description=step.get("description", ""),
                )
                for i, step in enumerate(
                    data.get("steps", [])
                )
            ]

            if kind in ("knowledge", "document") and steps:

                return PlanResult(
                    kind=kind,
                    intent=intent_result.intent,
                    steps=steps,
                    reasoning=data.get("reasoning", ""),
                )

        except Exception:
            pass

        return self.plan(
            message=message,
            intent_result=intent_result,
            context=context,
        )


def _infer_query_action(
        message: str
) -> str:

    """
    从消息推断查询任务动作（query_my_task 确定性兜底）
    """

    msg = message.strip()

    # 查看指定员工/部门任务（query_employee_task 由意图分支单独处理）
    if "部门任务" in msg or "部门情况" in msg:

        return "department_tasks"

    if (
        re.search(r"(?:查看|查|看).+的\s*任务", msg)
        and "我的任务" not in msg
    ):

        return "employee_tasks"

    return "list"


def _infer_submit_action(
        message: str
) -> str:

    """
    从消息推断提交任务动作（submit_task 确定性兜底）
    """

    msg = message.strip()

    if "确认" in msg:

        return "confirm"

    if "取消" in msg:

        return "cancel"

    if "全部任务" in msg or "所有任务" in msg:

        return "submit_all"

    if "提交" in msg or "进度" in msg:

        return "submit"

    if "完成" in msg:

        return "complete"

    return "submit"


# 全局单例
agent_planner = AgentPlanner()
