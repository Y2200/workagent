from pydantic import BaseModel, Field


class IntentType:

    """
    意图类型常量

    企业任务执行模型（Phase 7A）：
    - 任务意图拆分（query_my/query_employee/create/submit/remind/summary）
    - POLICY_QUERY = 制度查询
    - 兼容别名（TASK_MANAGEMENT/TASK_CREATE/TASK_REMIND/KNOWLEDGE_QUERY）
      值即新值，代码内统一用新常量
    """

    KNOWLEDGE_QUERY = "policy_query"

    DOCUMENT_OPERATION = "document_operation"

    AUDIT_QUERY = "audit_query"

    WORKFLOW_REQUEST = "workflow_request"

    RISK_ANALYSIS = "risk_analysis"

    # ======================
    # 企业任务意图（Phase 7A）
    # ======================

    # 员工查自己的任务
    QUERY_MY_TASK = "query_my_task"

    # 经理查员工/部门任务
    QUERY_EMPLOYEE_TASK = "query_employee_task"

    # 经理发布任务（带确认）
    CREATE_TASK = "create_task"

    # 员工提交/确认/取消/完成进度
    SUBMIT_TASK = "submit_task"

    # 经理提醒/督促员工
    REMIND_TASK = "remind_task"

    # 系统生成部门任务总结
    SUMMARY_TASK = "summary_task"

    # 制度查询
    POLICY_QUERY = "policy_query"

    SMALL_TALK = "small_talk"

    UNKNOWN = "unknown"

    # ======================
    # 兼容别名（值即新值）
    # ======================

    TASK_MANAGEMENT = QUERY_MY_TASK

    TASK_CREATE = CREATE_TASK

    TASK_REMIND = REMIND_TASK


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

    # 风险操作（如对外发邮件/批量通知/修改数据）需用户确认后才执行
    confirmation_required: bool = Field(
        default=False,
        description="是否需用户确认后执行"
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
