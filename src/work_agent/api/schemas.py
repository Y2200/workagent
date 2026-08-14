from datetime import datetime

from pydantic import BaseModel, ConfigDict


class LoginRequest(BaseModel):

    username: str

    password: str


class TokenResponse(BaseModel):

    access_token: str

    token_type: str = "bearer"


class UserOut(BaseModel):

    model_config = ConfigDict(
        from_attributes=True
    )

    id: int

    username: str

    department: str

    role: str

    # RBAC 角色码（SUPER_ADMIN 等），前端权限过滤用
    roles: list[str] = []

    created_at: datetime


class UserAdminOut(BaseModel):

    """
    用户管理列表项（企微绑定用）
    """

    model_config = ConfigDict(
        from_attributes=True
    )

    id: int

    username: str

    real_name: str = ""

    department: str

    role: str

    tenant_id: str

    wechat_user_id: str | None

    roles: list[str] = []

    created_at: datetime


class UserAdminPage(BaseModel):

    items: list[UserAdminOut]

    total: int


class CreateUserRequest(BaseModel):

    """
    Web 新建用户（user:manage）

    role: SUPER_ADMIN / TENANT_ADMIN / DEPARTMENT_ADMIN / USER
    tenant_id: SUPER_ADMIN 可设任意或空；租户管理员仅本租户
    """

    username: str

    password: str

    real_name: str = ""

    department: str = ""

    role: str = "USER"

    tenant_id: str = ""

    # 可选：创建即绑定企微 userid
    wechat_user_id: str = ""


class UpdateUserRequest(BaseModel):

    """
    编辑用户资料（None = 不修改）
    """

    real_name: str | None = None

    department: str | None = None

    role: str | None = None

    # SUPER_ADMIN 可改租户；有任务的用户禁止改租户
    tenant_id: str | None = None


class WechatBindRequest(BaseModel):

    """
    绑定企微 userid（空串=解绑）
    """

    wechat_user_id: str = ""


class TaskCreateRequest(BaseModel):

    title: str

    description: str = ""

    employee_id: int

    manager_id: int | None = None

    department: str = ""

    deadline: datetime | None = None

    # low / normal / high
    priority: str = "normal"


class TaskOut(BaseModel):

    model_config = ConfigDict(
        from_attributes=True
    )

    id: int

    tenant_id: str

    title: str

    description: str

    creator_id: int | None

    manager_id: int | None

    employee_id: int

    department: str

    deadline: datetime | None

    status: str

    progress: int

    priority: str

    created_at: datetime

    employee_username: str = ""


class TaskUpdateOut(BaseModel):

    model_config = ConfigDict(
        from_attributes=True
    )

    id: int

    task_id: int

    employee_id: int

    content: str

    progress: int

    ai_summary: str

    confirmed: bool

    created_at: datetime


class TaskDetailOut(TaskOut):

    updates: list[TaskUpdateOut] = []


class PermissionOut(BaseModel):

    model_config = ConfigDict(
        from_attributes=True
    )

    department: str

    role: str


class DocumentOut(BaseModel):

    model_config = ConfigDict(
        from_attributes=True
    )

    id: int

    filename: str

    file_type: str

    category: str

    uploader: str

    visibility: str

    status: str

    error_message: str | None

    chunk_count: int = 0

    created_at: datetime


class ChunkOut(BaseModel):

    model_config = ConfigDict(
        from_attributes=True
    )

    id: int

    milvus_id: int

    content: str

    chunk_index: int


class DocumentDetail(DocumentOut):

    permissions: list[PermissionOut] = []

    chunks: list[ChunkOut] = []


class KnowledgeHitOut(BaseModel):

    text: str

    source: str

    category: str

    score: float

    document_id: int | None

    document_filename: str = ""


class LogOut(BaseModel):

    model_config = ConfigDict(
        from_attributes=True
    )

    id: int

    request_id: str | None

    tenant_id: str

    user_id: int | None

    username: str | None = None

    department: str

    role: str

    channel: str

    question: str

    answer: str

    intent: str

    status: str

    error_type: str | None

    error_message: str | None

    retrieval_documents: list | None

    latency_ms: int

    token_usage: int

    agent_version: str = ""

    model_name: str = ""

    prompt_version: str = ""

    intent_confidence: float = 0.0

    tools_called: list | None = None

    created_at: datetime


class LogPage(BaseModel):

    items: list[LogOut]

    total: int

    page: int

    page_size: int


class OperationLogOut(BaseModel):

    model_config = ConfigDict(
        from_attributes=True
    )

    id: int

    tenant_id: str

    user_id: int | None

    username: str | None = None

    action: str

    target_type: str | None

    target_id: str | None

    ip: str | None

    user_agent: str | None

    created_at: datetime


class OperationLogPage(BaseModel):

    items: list[OperationLogOut]

    total: int

    page: int

    page_size: int


class SimilarDocOut(BaseModel):

    document_id: int

    filename: str

    matched_chunks: int

    max_score: float

    avg_score: float


class GraphNodeOut(BaseModel):

    id: int

    name: str

    type: str

    degree: int


class GraphEdgeOut(BaseModel):

    source: int

    target: int

    relation: str


class GraphOut(BaseModel):

    nodes: list[GraphNodeOut]

    edges: list[GraphEdgeOut]


class TraceOut(BaseModel):

    model_config = ConfigDict(
        from_attributes=True
    )

    id: int

    request_id: str

    tenant_id: str

    user_id: int | None

    channel: str

    status: str

    total_duration_ms: int

    span_count: int

    created_at: datetime


class TracePage(BaseModel):

    items: list[TraceOut]

    total: int

    page: int

    page_size: int


class TraceSpanOut(BaseModel):

    model_config = ConfigDict(
        from_attributes=True
    )

    id: int

    span_id: str

    parent_span_id: str | None

    name: str

    component: str

    duration_ms: int

    status: str

    error_type: str | None

    error_message: str | None

    attributes: dict | None


class WaterfallNodeOut(BaseModel):

    span_id: str

    name: str

    component: str

    duration_ms: int

    status: str

    attributes: dict | None

    children: list["WaterfallNodeOut"] = []


WaterfallNodeOut.model_rebuild()


class TraceDetailOut(BaseModel):

    trace: TraceOut

    spans: list[TraceSpanOut]

    waterfall: list[WaterfallNodeOut] = []


class ConfigOut(BaseModel):

    key: str

    value: object | None

    scope: str

    description: str

    updated_by: str

    updated_at: datetime | None


class ConfigUpdateRequest(BaseModel):

    value: object | None = None

    description: str = ""

    # tenant（租户覆盖）/ platform（平台级，需 SUPER_ADMIN）
    scope: str = "tenant"


class PromptListOut(BaseModel):

    name: str

    active_version: str | None

    content: str | None


class PromptHistoryOut(BaseModel):

    id: int

    name: str

    version: str

    status: str

    description: str

    updated_by: str

    activated_at: datetime | None

    created_at: datetime

    content: str


class PromptCreateDraftRequest(BaseModel):

    content: str

    description: str = ""


class PromptActivateRequest(BaseModel):

    version: str


class BudgetUpdateRequest(BaseModel):

    # 月度预算（元）；null = 不限制
    budget: float | None = None


class PermissionUpdateRequest(BaseModel):

    visibility: str = "public"

    departments: list[str] = []

    roles: list[str] = []

    user_ids: list[int] = []


class PermissionOut(BaseModel):

    visibility: str

    departments: list[str]

    roles: list[str]

    user_ids: list[int]

    # 更新时返回同步的 chunk 数
    synced_chunks: int = 0
