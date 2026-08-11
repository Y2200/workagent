from work_agent.agent.agents.base import BaseAgent
from work_agent.agent.agents.schemas import AgentResult
from work_agent.agent.schemas import IntentType
from work_agent.agent.tools.analysis_tool import AnalysisTool


class AnalysisAgent(BaseAgent):

    """
    风险/任务分析 Agent

    通过 AnalysisTool 检索相关制度并评估风险
    禁止直接访问 DB
    """

    name = "analysis_agent"

    description = "任务与风险分析"

    handled_kinds = ["risk"]


    def __init__(
            self,
            analysis_tool: AnalysisTool | None = None
    ):

        self.analysis_tool = analysis_tool or AnalysisTool()


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

        tool_result = self.analysis_tool.execute(
            query=message,
            user_context=context.to_user_context(),
            top_k=(
                step.args.get("top_k", 5)
                if step
                else 5
            ),
        )

        risk_level = tool_result["risk_level"]

        sources = [
            {
                "source": item.get("source", ""),
                "score": item.get("score", 0),
            }
            for item in tool_result["knowledge"]
        ]

        # 相关制度
        policies = [
            item.get("source", "")
            for item in tool_result["knowledge"]
        ]

        response = self._format_analysis(
            message,
            risk_level,
            policies,
            sources,
        )

        return AgentResult(
            agent=self.name,
            response=response,
            intent=IntentType.RISK_ANALYSIS,
            knowledge_sources=sources,
            permission_denied=tool_result["denied"],
            tools_called=["analysis_tool"],
            tool_calls=[{"tool": "analysis_tool", "action": "analyze"}],
        )


    def _format_analysis(
            self,
            message: str,
            risk_level: str,
            policies: list[str],
            sources: list
    ) -> str:

        risk_label = {
            "high": "高",
            "medium": "中",
            "low": "低",
        }.get(
            risk_level,
            risk_level,
        )

        lines = [
            f"风险分析（等级：{risk_label}）：",
            f"您反馈：{message}",
        ]

        if sources:

            lines.append(
                "相关制度：" + "、".join(
                    policy
                    for policy in policies
                    if policy
                )
            )

        else:

            lines.append("未检索到直接相关的制度。")

        if risk_level == "high":

            lines.append("建议：立即上报负责人并启动应急处置。")

        elif risk_level == "medium":

            lines.append("建议：尽快跟进处理并向上级反馈。")

        else:

            lines.append("建议：持续关注，按制度执行。")

        return "\n".join(lines)
