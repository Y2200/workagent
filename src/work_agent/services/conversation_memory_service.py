"""
会话记忆服务（Enterprise Agent 会话记忆，Phase 1）

- append / append_round：写会话消息（保存原始字段 role/scope/content/tool_name/metadata）
- get_recent：读取最近 N 轮作为 context window，**adapter 转换为 LangChain BaseMessage**
  （BaseMessage 仅存在于运行态，数据库保持原始字段）

不引入 LangChain ConversationMemory —— 自维护 conversation_messages 表。
不物理删除历史（完整会话留存；context window 由读取时限制）。

隔离铁律：消息经 conversation_id 关联（conversation 已按 tenant+user+channel 唯一），
A 用户的追问不污染 B。
"""

from work_agent.db.session import SessionLocal
from work_agent.repositories.conversation_repository import ConversationRepository


# 默认保留最近 6 轮（user + assistant = 12 条）
DEFAULT_ROUNDS = 6

MESSAGES_PER_ROUND = 2


class ConversationMemoryService:

    def __init__(
            self,
            repository: ConversationRepository | None = None
    ):

        self.repository = repository or ConversationRepository()


    def append(
            self,
            conversation_id,
            *,
            role: str,
            content: str,
            scope: str = "chat",
            tenant_id: str = "",
            user_id: int | None = None,
            tool_name: str | None = None,
            extra: dict | None = None
    ) -> None:

        """
        追加一条消息（写原始字段，不存 BaseMessage）

        role: user / assistant / tool / system
        """

        if not conversation_id:
            return

        db = SessionLocal()

        try:

            self.repository.append_message(
                db,
                conversation_id=int(conversation_id),
                role=role,
                content=content,
                scope=scope,
                tenant_id=tenant_id,
                user_id=user_id,
                tool_name=tool_name,
                extra=extra,
            )

        finally:

            db.close()


    def append_round(
            self,
            conversation_id,
            user_message: str,
            assistant_message: str,
            *,
            tenant_id: str = "",
            user_id: int | None = None
    ) -> None:

        """
        追加一轮完整对话（user + assistant 两条，scope=chat）
        """

        if not conversation_id:
            return

        if not user_message and not assistant_message:
            return

        db = SessionLocal()

        try:

            if user_message:
                self.repository.append_message(
                    db,
                    conversation_id=int(conversation_id),
                    role="user",
                    scope="chat",
                    content=user_message,
                    tenant_id=tenant_id,
                    user_id=user_id,
                )

            if assistant_message:
                self.repository.append_message(
                    db,
                    conversation_id=int(conversation_id),
                    role="assistant",
                    scope="chat",
                    content=assistant_message,
                    tenant_id=tenant_id,
                    user_id=user_id,
                )

        finally:

            db.close()


    def get_recent(
            self,
            conversation_id,
            rounds: int = DEFAULT_ROUNDS,
            scope: str | None = None
    ) -> list:

        """
        读取最近 N 轮作为 context window，返回 list[BaseMessage]（运行态）

        **只限窗口，不删除历史**。无会话 id 返回 []（防御）。
        """

        if not conversation_id:
            return []

        db = SessionLocal()

        try:

            rows = self.repository.get_recent_messages(
                db,
                conversation_id=int(conversation_id),
                limit=rounds * MESSAGES_PER_ROUND,
                scope=scope,
            )

            return [
                self.to_basemessage(row)
                for row in rows
            ]

        finally:

            db.close()


    # ======================
    # Adapter：DB 原始字段 ↔ LangChain BaseMessage
    # ======================

    @staticmethod
    def to_basemessage(row):

        """
        DB 行 → LangChain BaseMessage（运行态）

        role: user → HumanMessage / assistant → AIMessage / tool → ToolMessage
              / system → SystemMessage
        """

        from langchain_core.messages import (
            AIMessage,
            HumanMessage,
            SystemMessage,
            ToolMessage,
        )

        role = row.role

        content = row.content

        if role == "assistant":
            return AIMessage(content=content)

        if role == "tool":
            return ToolMessage(
                content=content,
                tool_call_id=(
                    str(row.id)
                    or "tool-call"
                ),
            )

        if role == "system":
            return SystemMessage(content=content)

        return HumanMessage(content=content)


    @staticmethod
    def serialize_history(history) -> str:

        """
        list[BaseMessage] → 纯文本（rewrite prompt / 回答上下文用）
        """

        if not history:
            return ""

        lines = []

        for msg in history:

            role = msg.type

            name = (
                "用户"
                if role == "human"
                else "助手"
            )

            lines.append(
                f"{name}：{msg.content}"
            )

        return "\n".join(lines)


# 全局单例
conversation_memory_service = ConversationMemoryService()
