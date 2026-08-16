"""
RAG 查询改写器（Enterprise Agent 会话记忆，Phase 2）

结合 chat_history 把追问（如"那经理呢？"）改写为完整独立查询词，再检索 Milvus。

- **指代词优先** `_is_follow_up`：以"那/这个/那个/它/他/她/然后/多少钱"开头，
  或含"呢"、"？"短尾 → 判定为追问（不依赖字数）
- LLM 改写为主 + 确定性兜底 `_rule_rewrite`，失败回退原 query（不破坏现有 RAG）
- **chat_history 只作为文本进 rewrite prompt，永不 embedding 进 Milvus**
- 放 agent/ 根目录（避开契约扫描 agent/agents + agent/tools）
"""

from work_agent.core.prompt_manager import prompt_manager
from work_agent.services.conversation_memory_service import (
    conversation_memory_service,
)

# 指代词/追问开头
_FOLLOW_UP_PREFIXES = (
    "那",
    "这个",
    "那个",
    "它",
    "他",
    "她",
    "然后",
    "多少钱",
    "这样",
    "那这个",
    "那刚才",
)

# 追问短尾
_FOLLOW_UP_SUFFIXES = ("呢", "？", "?")


class QueryRewriter:

    """
    RAG 查询改写器
    """

    def __init__(
            self,
            memory_service=None,
            llm=None
    ):

        self.memory_service = memory_service or conversation_memory_service

        self.llm = llm  # 惰性：None 时用 get_llm()


    def rewrite_query(
            self,
            query: str,
            history=None,
            rounds: int = 6
    ) -> str:

        """
        改写查询词：追问 → 完整独立查询词；否则原样

        返回 str（只改查询词，不改检索逻辑）
        """

        if not query or not query.strip():
            return query or ""

        # 无历史 → 原样（0 成本）
        if not history:
            return query

        # 独立问题 → 原样（指代词优先判定，非独立才 rewrite）
        if not self._is_follow_up(query):
            return query

        # 追问 → LLM 改写，失败回退确定性
        rule = self._rule_rewrite(query, history)

        try:

            rewritten = self._llm_rewrite(query, history)

            if rewritten and rewritten.strip():

                return rewritten.strip()

        except Exception:
            pass

        return rule or query


    # ======================
    # 追问判定（指代词优先，不依赖字数）
    # ======================

    @staticmethod
    def _is_follow_up(query: str) -> bool:

        """
        判断是否追问（指代词/疑问短尾优先）

        - 以"那/这个/那个/它/他/她/然后/多少钱"等开头 → 追问
        - 含"呢"、"？" 短尾 → 追问
        - 其余（独立问题）→ False（不 rewrite）
        """

        q = query.strip()

        if not q:
            return False

        if q.startswith(_FOLLOW_UP_PREFIXES):
            return True

        if any(
            q.endswith(s)
            for s in _FOLLOW_UP_SUFFIXES
        ):
            return True

        return False


    # ======================
    # 确定性兜底改写
    # ======================

    @staticmethod
    def _rule_rewrite(
            query: str,
            history
    ) -> str | None:

        """
        确定性兜底：从追问提取实体 + 结合上轮 user 消息拼完整查询

        例："那经理呢？" + 上轮"差旅住宿标准是什么"
          → 提取实体"经理"，上轮去掉疑问尾 → "差旅住宿标准"
          → 拼 "差旅住宿标准 经理"
        """

        import re

        q = query.strip()

        # 提取追问实体：「那X呢/那X？」→ X
        entity = ""

        m = re.match(
            r"^那(.+?)[呢嘛]?[？?]?\s*$",
            q,
        )

        if m:
            entity = m.group(1).strip()

        # 无实体（如"那是什么"）→ 无法确定性改写
        if not entity:
            return None

        # 上轮 user 消息作为基底
        base = ""

        for msg in reversed(history or []):

            if getattr(msg, "type", "") == "human":

                base = str(msg.content or "").strip()

                break

        if not base:
            return None

        # 去掉基底疑问尾（是什么/是多少/有哪些/标准等疑问词）
        base = re.sub(
            r"[？?]$",
            "",
            base,
        )

        # 拼完整查询：基底 + 实体
        return f"{base} {entity}"


    # ======================
    # LLM 改写
    # ======================

    def _llm_rewrite(
            self,
            query: str,
            history
    ) -> str:

        loaded = prompt_manager.load(
            "conversation_rewrite"
        )

        prompt = loaded["content"].format(
            query=query,
            history=self._serialize(history),
        )

        llm = self._get_llm()

        result = llm.invoke(prompt)

        return str(
            getattr(result, "content", result) or ""
        )


    def _serialize(self, history) -> str:

        return conversation_memory_service.serialize_history(
            history
        )


    def _get_llm(self):

        if self.llm is None:

            from work_agent.agent.llm import get_llm

            self.llm = get_llm()

        return self.llm


# 全局单例
query_rewriter = QueryRewriter()
