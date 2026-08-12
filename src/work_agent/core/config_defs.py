"""
Agent 配置项定义（内置默认值）

配置中心内置默认注册表：
- 无 DB 记录时使用 default
- default=None 表示"未设置"（沿用系统级 config.py 或不受限制）
"""

CONFIG_DEFINITIONS = {
    "agent.model": {
        "default": None,
        "description": "Agent 使用的 LLM 模型（None=沿用 settings.model_name）",
    },
    "agent.temperature": {
        "default": None,
        "description": "LLM 采样温度（None=沿用 settings.model_temperature）",
    },
    "agent.default_top_k": {
        "default": 5,
        "description": "知识检索默认 top_k",
    },
    "agent.tools.enabled": {
        "default": None,
        "description": "启用的工具列表（None=全部启用）",
    },
    "cost.monthly_budget": {
        "default": None,
        "description": "月度 LLM 预算（元；None=不限制）",
    },
}
