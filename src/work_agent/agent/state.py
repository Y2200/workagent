from typing_extensions import TypedDict


class AgentState(TypedDict, total=False):

    user: str

    message: str


    # 用户信息
    tenant_id: str
    user_id: int | None
    department: str
    role: str


    # 任务分析
    task_type: str
    task_status: str

    # 新增
    intent: str


    # 知识分类
    knowledge_category: str


    retrieval_status: str

    permission_denied: bool

    # 风险
    risk_level: str
    risk_reason: str


    # RAG
    knowledge: str
    knowledge_sources: list

    next_action: str

    task_supervision_result: str
    supervision_status: str
    supervision_action: str

    supervision_target: str

    supervision_deadline: str
    supervision_channel: str

    supervision_priority: str

    notify_result: str

    # 回复
    response: str

