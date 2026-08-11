"""
Agent Router 包

- intent_router：LLM 意图路由（Phase 4-1）
- legacy：旧规则 router_node（向后兼容，逐步下线）
"""

from work_agent.agent.router.intent_router import IntentRouter
from work_agent.agent.router.legacy import router_node


__all__ = [
    "IntentRouter",
    "router_node"
]
