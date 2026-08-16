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
            knowledge_tool: KnowledgeTool | None = None,
            query_rewriter=None
    ):

        self.knowledge_tool = knowledge_tool or KnowledgeTool()

        self.llm = get_llm()

        # RAG 查询改写（会话记忆，Phase 2；失败静默回退原 query）
        self.query_rewriter = query_rewriter

        if self.query_rewriter is None:

            from work_agent.agent.query_rewriter import query_rewriter

            self.query_rewriter = query_rewriter


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

        # ======================
        # RAG 会话记忆：结合 chat_history 改写查询词
        # context.chat_history 由 runtime context_builder 统一加载（Phase 1）
        # rewrite 失败 → 返回原 query → 完全退化为现状
        # 答案 prompt 仍用原始 message（回答"那经理呢？"），知识片段来自改写后检索
        # ======================

        history = (
            getattr(context, "chat_history", None)
            or []
        )

        try:

            search_query = self.query_rewriter.rewrite_query(
                message,
                history,
            )

        except Exception:

            search_query = message

        tool_result = self.knowledge_tool.execute(
            query=search_query,
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
        # Enterprise Knowledge（Phase 10）：
        # 权限/资格类问题（"我能不能申请远程办公"）→ 追加用户画像
        # 制度(RAG) + 用户身份/组织（context 注入，不查 DB 不持久化）
        # ======================

        user_profile = ""

        from work_agent.agent.organization import (
            build_user_profile,
            is_permission_query,
        )

        if is_permission_query(message):

            user_profile = build_user_profile(context)

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
            user_profile=(
                user_profile
                or "（无，非权限类问题）"
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
