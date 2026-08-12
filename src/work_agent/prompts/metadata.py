"""
Prompt 元数据注册表

版本管理基础，未来支持 A/B 测试、灰度发布
"""

PROMPT_METADATA = {
    "intent_router": {
        "version": "1.0",
        "description": "意图识别",
        "variables": [
            "message",
            "user_context",
            "tenant_context",
        ],
    },
    "task_analysis": {
        "version": "1.0",
        "description": "任务分析（类型/状态/意图/分类）",
        "variables": [
            "message",
        ],
    },
    "risk_analysis": {
        "version": "1.0",
        "description": "风险判断",
        "variables": [
            "user",
            "department",
            "role",
            "task_type",
            "task_status",
            "intent",
        ],
    },
    "task_supervision": {
        "version": "1.0",
        "description": "是否需要督导",
        "variables": [
            "user",
            "department",
            "role",
            "task_type",
            "task_status",
            "risk_level",
            "knowledge",
        ],
    },
    "supervision_action": {
        "version": "1.0",
        "description": "督导动作选择",
        "variables": [
            "user",
            "department",
            "role",
            "task_type",
            "risk_level",
            "risk_reason",
            "task_supervision_result",
        ],
    },
    "response": {
        "version": "1.0",
        "description": "最终回复生成",
        "variables": [
            "user",
            "department",
            "role",
            "message",
            "task_status",
            "risk_level",
            "supervision_result",
            "notify_result",
            "knowledge",
            "knowledge_sources",
        ],
    },
    "response_generate": {
        "version": "1.0",
        "description": "备用回复生成",
        "variables": [
            "user",
            "task_type",
            "risk",
            "knowledge",
            "message",
        ],
    },
    # ======================
    # 未来 Prompt（Phase 4 规划）
    # ======================
    "knowledge_answer": {
        "version": "1.0",
        "description": "知识库回答",
        "variables": [
            "query",
            "knowledge",
            "user_context",
        ],
    },
    "tool_selector": {
        "version": "1.0",
        "description": "工具选择",
        "variables": [
            "message",
            "intent",
            "entities",
            "available_tools",
        ],
    },
    "workflow_planner": {
        "version": "1.0",
        "description": "工作流规划",
        "variables": [
            "message",
            "intent",
            "entities",
            "available_tools",
        ],
    },
    # ======================
    # 知识智能 Prompt（P5-4）
    # ======================
    "doc_classifier": {
        "version": "1.0",
        "description": "文档自动分类",
        "variables": [
            "title",
            "content",
        ],
    },
    "kg_extract": {
        "version": "1.0",
        "description": "知识图谱实体/关系抽取",
        "variables": [
            "title",
            "content",
            "entity_limit",
        ],
    },
}
