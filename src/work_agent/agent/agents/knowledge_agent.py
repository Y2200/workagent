import json

from work_agent.agent.agents.base import BaseAgent
from work_agent.agent.agents.schemas import AgentResult
from work_agent.agent.llm import get_llm
from work_agent.agent.schemas import IntentType
from work_agent.agent.tools.knowledge_tool import KnowledgeTool
from work_agent.core.audit_logger import TokenUsageCallback
from work_agent.core.prompt_manager import prompt_manager


class KnowledgeAgent(BaseAgent):

    """
    知识问答 Agent

    通过 KnowledgeTool 检索 + LLM 生成回答
    禁止直接访问 DB
    """

    name = "knowledge_agent"

    description = "企业知识问答"

    handled_kinds = ["knowledge"]


    def __init__(
            self,
            knowledge_tool: KnowledgeTool | None = None
    ):

        self.knowledge_tool = knowledge_tool or KnowledgeTool()

        self.llm = get_llm()


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

        tool_result = self.knowledge_tool.execute(
            query=message,
            user_context=context.to_user_context(),
            top_k=(
                step.args.get("top_k", 5)
                if step
                else 5
            ),
        )

        results = tool_result["results"]

        knowledge_text = "\n".join(
            [
                item["text"]
                for item in results
            ]
        )

        sources = [
            {
                "source": item.get("source", ""),
                "score": item.get("score", 0),
            }
            for item in results
        ]

        # ======================
        # Response Generation
        # ======================

        loaded = prompt_manager.load(
            "knowledge_answer"
        )

        context.prompt_version = loaded["version"]

        callback = TokenUsageCallback()

        prompt = loaded["content"].format(
            query=message,
            knowledge=(
                knowledge_text
                or "（未检索到相关制度）"
            ),
            user_context=json.dumps(
                context.to_user_context(),
                ensure_ascii=False,
            ),
        )

        response = self.llm.invoke(
            prompt,
            config={
                "callbacks": [
                    callback
                ]
            }
        )

        return AgentResult(
            agent=self.name,
            response=response.content,
            intent=IntentType.KNOWLEDGE_QUERY,
            knowledge_sources=sources,
            permission_denied=tool_result["denied"],
            token_usage=callback.total,
            tools_called=["knowledge_tool"],
            tool_calls=[{"tool": "knowledge_tool", "action": "search"}],
        )
