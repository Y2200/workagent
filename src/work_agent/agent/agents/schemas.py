from pydantic import BaseModel, Field


class AgentResult(BaseModel):

    """
    专业 Agent 执行结果
    """

    agent: str = Field(
        description="执行 Agent 名"
    )

    response: str = Field(
        default="",
        description="回复内容"
    )

    intent: str = Field(
        default="",
        description="关联意图"
    )

    knowledge_sources: list = Field(
        default_factory=list,
        description="命中的文档"
    )

    permission_denied: bool = Field(
        default=False,
        description="是否权限拒绝"
    )

    token_usage: int = Field(
        default=0,
        description="token 用量"
    )

    tools_called: list[str] = Field(
        default_factory=list,
        description="调用的工具"
    )

    # 工具调用详情（tool + action，供评测）
    tool_calls: list[dict] = Field(
        default_factory=list,
        description="工具调用详情"
    )

    # 风险操作是否经用户确认（Enterprise Agent；None=不适用）
    confirmed: bool | None = Field(
        default=None,
        description="是否经用户确认"
    )

    # 受约束 Agent Loop 实际执行步数（None=非循环路径）
    # agent 字段保持底层能力名（knowledge_agent/analysis_agent）兼容既有评测断言，
    # 循环已执行由 loop_steps / tool_calls 长度可观测
    loop_steps: int | None = Field(
        default=None,
        description="受约束 Agent Loop 实际执行步数"
    )


    def to_dict(self) -> dict:

        """
        转换为 Runtime 审计所需字段
        """

        return {
            "response": self.response,
            "intent": self.intent,
            "knowledge_sources": self.knowledge_sources,
            "permission_denied": self.permission_denied,
            "token_usage": self.token_usage,
            "tools_called": self.tools_called,
            "tool_calls": self.tool_calls,
            "confirmed": self.confirmed,
            "loop_steps": self.loop_steps,
        }
