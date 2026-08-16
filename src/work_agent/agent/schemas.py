from pydantic import BaseModel, Field


class IntentType:

    """
    意图类型常量
    """

    KNOWLEDGE_QUERY = "knowledge_query"

    DOCUMENT_OPERATION = "document_operation"

    AUDIT_QUERY = "audit_query"

    WORKFLOW_REQUEST = "workflow_request"

    RISK_ANALYSIS = "risk_analysis"

    TASK_MANAGEMENT = "task_management"

    # Enterprise Agent：任务发布（管理员，带确认）
    TASK_CREATE = "task_create"

    SMALL_TALK = "small_talk"

    UNKNOWN = "unknown"


class PlanStep(BaseModel):

    """
    计划步骤
    """

    step_id: int = Field(
        description="步骤序号"
    )

    tool: str = Field(
        description="工具名"
    )

    action: str = Field(
        default="",
        description="工具操作"
    )

    args: dict = Field(
        default_factory=dict,
        description="操作参数"
    )

    description: str = Field(
        default="",
        description="步骤说明"
    )


class PlanResult(BaseModel):

    """
    规划结果

    kind：
    - knowledge：知识问答（knowledge_tool 步骤）
    - document：文档/权限操作（document_tool/permission_tool 步骤）
    - legacy：督导/风险等其他路径（旧工作流）
    """

    kind: str = Field(
        description="计划类型（knowledge/document/legacy）"
    )

    intent: str = Field(
        default="",
        description="关联意图"
    )

    steps: list[PlanStep] = Field(
        default_factory=list,
        description="执行步骤"
    )

    reasoning: str = Field(
        default="",
        description="规划依据"
    )


class IntentResult(BaseModel):

    """
    Intent Router 结构化输出
    """

    intent: str = Field(
        description="意图类型（knowledge_query/document_operation/workflow_request/risk_analysis/small_talk/unknown）"
    )

    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="置信度 0-1"
    )

    entities: dict = Field(
        default_factory=dict,
        description="提取的实体（如 task_type/category/文档关键词）"
    )

    need_tool: bool = Field(
        default=False,
        description="是否需要调用工具"
    )

    tool: str = Field(
        default="",
        description="需要的工具名（knowledge_tool/document_tool/permission_tool/audit_tool）"
    )

    reasoning: str = Field(
        default="",
        description="推理过程"
    )
