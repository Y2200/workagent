"""
Agent 包（专业 Agent）

- base：Agent 基类
- schemas：AgentResult
- registry：AgentRegistry
- supervisor：SupervisorAgent（协调者）
- knowledge_agent / operation_agent / analysis_agent
"""

from work_agent.agent.agents.base import BaseAgent
from work_agent.agent.agents.registry import agent_registry
from work_agent.agent.agents.schemas import AgentResult
from work_agent.agent.agents.supervisor import supervisor_agent


__all__ = [
    "BaseAgent",
    "AgentResult",
    "agent_registry",
    "supervisor_agent",
]
