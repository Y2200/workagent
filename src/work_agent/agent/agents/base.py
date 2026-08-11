from abc import ABC, abstractmethod


class BaseAgent(ABC):

    """
    专业 Agent 基类

    规范：
    - 不允许直接访问 DB
    - 必须通过 Tool
    - 必须经过 RBAC（工具层校验 + 上下文权限）
    - 必须写 Audit（由 Runtime/Supervisor 统一记录）
    """

    name: str = ""

    description: str = ""

    # 处理的计划类型（plan.kind）
    handled_kinds: list[str] = []


    @abstractmethod
    def run(
            self,
            *,
            context,
            plan,
            message: str
    ) -> "AgentResult":

        """
        执行 Agent 任务，返回结构化结果
        """
