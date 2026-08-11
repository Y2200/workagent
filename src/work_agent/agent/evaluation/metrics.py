class Metrics:

    """
    评测指标计算

    - intent_accuracy：意图识别准确率
    - tool_accuracy：工具选择准确率
    - agent_routing_accuracy：Agent 分派准确率
    - permission_safety_rate：权限安全率（必须 100%）
    - tenant_isolation_rate：租户隔离率（必须 100%）
    - regression_rate：回归通过率
    """

    def __init__(
            self,
            results: list[dict]
    ):

        self.results = results


    def _cases(
            self,
            category: str
    ) -> list[dict]:

        return [
            result
            for result in self.results
            if result["category"] == category
        ]


    @staticmethod
    def _rate(cases: list[dict]) -> float:

        if not cases:
            return 0.0

        passed = sum(
            1
            for case in cases
            if case["passed"]
        )

        return round(
            passed / len(cases),
            4
        )


    def intent_accuracy(self) -> float:

        return self._rate(
            self._cases("intent")
        )


    def tool_accuracy(self) -> float:

        return self._rate(
            self._cases("tool")
        )


    def agent_routing_accuracy(self) -> float:

        return self._rate(
            self._cases("agent")
        )


    def permission_safety_rate(self) -> float:

        # 所有安全用例（权限拒绝 + 租户隔离）都必须安全处理
        return self._rate(
            self._cases("security")
        )


    def tenant_isolation_rate(self) -> float:

        isolation_cases = [
            result
            for result in self._cases("security")
            if result.get("check") == "tenant_isolation"
        ]

        return self._rate(
            isolation_cases
        )


    def regression_rate(self) -> float:

        return self._rate(
            self._cases("regression")
        )


    def compute(self) -> dict:

        return {
            "intent_accuracy": self.intent_accuracy(),
            "tool_accuracy": self.tool_accuracy(),
            "agent_routing_accuracy": self.agent_routing_accuracy(),
            "permission_safety_rate": self.permission_safety_rate(),
            "tenant_isolation_rate": self.tenant_isolation_rate(),
            "regression_rate": self.regression_rate(),
        }
