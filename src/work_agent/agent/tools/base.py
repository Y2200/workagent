from abc import ABC, abstractmethod


class BaseTool(ABC):

    """
    Agent 工具基类

    所有工具必须提供 name/description/input_schema/execute
    禁止工具直接访问数据库（统一经 Service）
    """

    name: str = ""

    description: str = ""

    input_schema: dict = {}


    @abstractmethod
    def execute(
            self,
            **kwargs
    ) -> dict:

        """
        执行工具，返回结构化结果
        """
