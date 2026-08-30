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
    "agent.loop.enabled": {
        "default": True,
        "description": "受约束 Agent Loop 是否启用（只读意图：知识/制度查询、风险分析）",
    },
    "agent.loop.max_steps": {
        "default": 5,
        "description": "受约束 Agent Loop 最大工具执行步数（硬上限，防无限循环）",
    },
    "agent.loop.max_empty_observations": {
        "default": 2,
        "description": "连续空检索达到该值 → 熔断（RAG 查不到就停止，不反复重试换 query）",
    },
    "agent.loop.max_tokens_budget": {
        "default": 8000,
        "description": "单次 Loop 累计 token 预算（超限强制兜底；0=不限制）",
    },
    "agent.loop.max_duration_seconds": {
        "default": 60,
        "description": "单次 Loop 最大耗时秒数（超时强制兜底；0=不限制）。"
        "实测 DeepSeek 单次调用可达 10-30s，多步循环需留足余量，15s 会误杀正常多步",
    },
    "agent.loop.min_similarity": {
        "default": 0.45,
        "description": "RAG 质量门控：最高检索分低于该值视为无有效知识，停止循环。"
        "bge-small-zh 余弦分普遍 0.5-0.7（实测相关文档可低至 0.59），"
        "0.45 只拦明显无关的垃圾召回，可按业务调高",
    },
    "cost.monthly_budget": {
        "default": None,
        "description": "月度 LLM 预算（元；None=不限制）",
    },
}
