import json

from work_agent.agent.context import AgentContext
from work_agent.agent.llm import get_llm
from work_agent.agent.schemas import IntentType, PlanResult, PlanStep
from work_agent.agent.tools.registry import tool_registry
from work_agent.agent.tools.selector import tool_selector
from work_agent.core.prompt_manager import prompt_manager
from work_agent.core.utils import parse_json


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
        # （LLM 可能在 workflow_request / task_management 间摇摆，此处确定性归一）
        # ======================

        if (
            intent == IntentType.WORKFLOW_REQUEST
            and ("任务" in message or "进度" in message)
        ):

            intent = IntentType.TASK_MANAGEMENT

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

        if intent == IntentType.TASK_MANAGEMENT:

            action = (
                intent_result.entities.get("action")
                or ""
            )

            if action not in (
                "list",
                "detail",
                "submit",
                "submit_all",
                "confirm",
                "cancel",
                "complete",
            ):

                # LLM 未给出 action 时从消息推断（确定性兜底）
                action = _infer_task_action(message)

            # 批量语义确定性强覆盖（LLM 可能返回 submit）
            if (
                "全部任务" in message
                or "所有任务" in message
            ):

                action = "submit_all"

            return PlanResult(
                kind="task",
                intent=intent,
                steps=[
                    PlanStep(
                        step_id=1,
                        tool="task_tool",
                        action=action,
                        description="任务督导",
                    ),
                ],
                reasoning=f"任务督导：执行 {action}",
            )

        # 其他（督导/闲聊/未知）
        return PlanResult(
            kind="legacy",
            intent=intent,
            steps=[],
            reasoning="督导/闲聊等路径：委托旧工作流",
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


def _infer_task_action(
        message: str
) -> str:

    """
    从消息推断任务动作（确定性兜底）
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

    return "list"


# 全局单例
agent_planner = AgentPlanner()
