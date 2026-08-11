from dataclasses import dataclass, field

from uuid import uuid4


@dataclass
class AgentContext:

    """
    统一 Agent 上下文

    所有 Agent 节点/工具必须通过本上下文获取用户与租户信息
    """

    request_id: str

    tenant_id: str

    user_id: int | None

    username: str

    department: str

    role: str

    permissions: set[str] = field(
        default_factory=set
    )

    conversation_id: str = ""

    channel: str = "wechat"

    prompt_version: str = ""

    model_name: str = ""

    agent_version: str = ""


    @classmethod
    def build(
            cls,
            *,
            user,
            channel: str = "wechat",
            permissions: set[str] | None = None,
            conversation_id: str | None = None,
            model_name: str = "",
            agent_version: str = ""
    ) -> "AgentContext":

        """
        从 User 构建上下文
        """

        return cls(
            request_id=str(uuid4()),
            tenant_id=user.tenant_id,
            user_id=user.id,
            username=user.username or "",
            department=user.department,
            role=user.role,
            permissions=set(
                permissions or []
            ),
            conversation_id=conversation_id or str(uuid4()),
            channel=channel,
            model_name=model_name,
            agent_version=agent_version,
        )


    def to_user_context(self) -> dict:

        """
        转换为 RAG 检索所需 user_context
        """

        return {
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "department": self.department,
            "role": self.role,
        }


    def to_audit_fields(self) -> dict:

        """
        审计扩展字段（P4-6 落库）
        """

        return {
            "agent_version": self.agent_version,
            "model_name": self.model_name,
            "prompt_version": self.prompt_version,
        }
