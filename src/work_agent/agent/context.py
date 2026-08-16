from dataclasses import dataclass, field

from typing import TYPE_CHECKING

from uuid import uuid4

if TYPE_CHECKING:

    from langchain_core.messages import BaseMessage


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

    # RBAC 角色码（如 SUPER_ADMIN/DEPARTMENT_ADMIN/USER），Runtime 注入
    # 用于部门作用域校验等角色维度判断（role 字段是 User.role 自由文本，非角色码）
    role_codes: set[str] = field(
        default_factory=set
    )

    # System Agent 身份（Phase 7A）：is_system=True 跳过用户角色校验，
    # 但执行 System Permission Check（system:scan/task:remind/report:send）
    is_system: bool = False

    # 多部门隔离预留（Phase 7A）：department_id 外键，当前 User 无该列恒空
    department_id: str = ""

    conversation_id: str = ""

    # 会话记忆（P2）：最近 N 轮 LangChain BaseMessage（运行态）
    # 由 runtime context_builder 统一加载，所有 Agent 分支共享
    # 只辅助 LLM 理解上下文，不参与 employee_id/deadline/RBAC 等业务决策
    chat_history: list = field(
        default_factory=list
    )

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
            role_codes: set[str] | None = None,
            conversation_id: str | None = None,
            model_name: str = "",
            agent_version: str = "",
            request_id: str | None = None,
            is_system: bool = False,
            department_id: str = ""
    ) -> "AgentContext":

        """
        从 User 构建上下文

        request_id 由调用方注入（与审计/追踪对齐），缺省自动生成
        role_codes 由 Runtime 注入（RBAC 角色码，部门作用域校验用）
        is_system 由 System Agent 链路注入（Phase 7A）
        """

        return cls(
            request_id=request_id or str(uuid4()),
            tenant_id=user.tenant_id,
            user_id=user.id,
            username=user.username or "",
            department=user.department,
            role=user.role,
            permissions=set(
                permissions or []
            ),
            role_codes=set(
                role_codes or []
            ),
            is_system=is_system,
            department_id=department_id,
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
