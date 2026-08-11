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
            selector=None
    ):

        self.llm = llm or get_llm()

        self.selector = selector or tool_selector

        self.last_prompt_version = ""


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
                        args={"top_k": 5},
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
                        args={"top_k": 5},
                        description="风险/任务分析",
                    ),
                ],
                reasoning="风险分析：检索制度并评估风险",
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


# 全局单例
agent_planner = AgentPlanner()
