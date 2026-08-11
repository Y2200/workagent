from work_agent.agent.agents.registry import agent_registry
from work_agent.agent.agents.schemas import AgentResult
from work_agent.core.audit_logger import TokenUsageCallback


class SupervisorAgent:

    """
    主管 Agent

    根据计划选择专业 Agent 并协调执行：
    - knowledge → KnowledgeAgent
    - document → OperationAgent
    - risk → AnalysisAgent
    - legacy → 旧 LangGraph 工作流（督导等）
    """

    name = "supervisor"

    description = "协调各专业 Agent 执行任务"


    def __init__(
            self,
            registry=None,
            legacy_workflow=None
    ):

        self.registry = registry or agent_registry

        # 旧工作流（懒加载，避免循环依赖）
        self.legacy_workflow = legacy_workflow


    def dispatch(
            self,
            *,
            context,
            plan,
            message: str
    ) -> AgentResult:

        """
        按计划分派到专业 Agent
        """

        agent = self.registry.get_for_kind(
            plan.kind
        )

        if agent:

            return agent.run(
                context=context,
                plan=plan,
                message=message,
            )

        # legacy 路径（督导/闲聊/未知）
        return self._run_legacy(
            context,
            plan,
            message,
        )


    def _run_legacy(
            self,
            context,
            plan,
            message: str
    ) -> AgentResult:

        workflow = self._get_legacy_workflow()

        callback = TokenUsageCallback()

        result = workflow.invoke(
            {
                "user":
                    context.username,

                "message":
                    message,

                "tenant_id":
                    context.tenant_id,

                "user_id":
                    context.user_id,

                "department":
                    context.department,

                "role":
                    context.role,
            },
            config={
                "callbacks": [
                    callback
                ]
            },
        )

        return AgentResult(
            agent="legacy_workflow",
            response=result.get(
                "response",
                ""
            ),
            intent=result.get(
                "intent",
                plan.intent if plan else "",
            ),
            knowledge_sources=result.get(
                "knowledge_sources",
                [],
            ),
            permission_denied=bool(
                result.get(
                    "permission_denied",
                    False,
                )
            ),
            token_usage=callback.total,
            tools_called=[],
            tool_calls=[],
        )


    def _get_legacy_workflow(self):

        if self.legacy_workflow is None:

            from work_agent.agent.workflow import workflow

            self.legacy_workflow = workflow

        return self.legacy_workflow


# 全局单例
supervisor_agent = SupervisorAgent()
