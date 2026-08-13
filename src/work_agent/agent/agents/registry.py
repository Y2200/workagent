from work_agent.agent.agents.analysis_agent import AnalysisAgent
from work_agent.agent.agents.knowledge_agent import KnowledgeAgent
from work_agent.agent.agents.operation_agent import OperationAgent
from work_agent.agent.agents.task_agent import TaskAgent


class AgentRegistry:

    """
    专业 Agent 注册表
    """

    def __init__(
            self,
            agents: list | None = None
    ):

        self._agents: dict[str, object] = {}

        for agent in (
            agents
            or [
                KnowledgeAgent(),
                OperationAgent(),
                AnalysisAgent(),
                TaskAgent(),
            ]
        ):

            self.register(agent)


    def register(self, agent) -> None:

        self._agents[agent.name] = agent


    def get(self, name: str):

        return self._agents.get(name)


    def get_for_kind(self, kind: str):

        """
        按计划类型返回可处理的 Agent
        """

        for agent in self._agents.values():

            if kind in agent.handled_kinds:

                return agent

        return None


    def list_agents(self) -> list[dict]:

        return [
            {
                "name": agent.name,
                "description": agent.description,
                "kinds": agent.handled_kinds,
            }
            for agent in self._agents.values()
        ]


# 全局单例
agent_registry = AgentRegistry()
