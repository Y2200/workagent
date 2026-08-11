from work_agent.agent.tools.base import BaseTool


# 高危事件关键词（与 risk 规则一致）
HIGH_RISK_KEYWORDS = [
    "安全事故",
    "生产事故",
    "人身伤害",
    "重大投诉",
    "财务异常",
]

MEDIUM_RISK_KEYWORDS = [
    "延期",
    "未提交",
    "忘记",
    "超期",
    "异常",
]


class AnalysisTool(BaseTool):

    """
    风险/任务分析工具

    检索相关制度 + 规则风险评估
    内部经 RAGService，禁止直接访问 DB
    """

    name = "analysis_tool"

    description = "任务/风险分析（检索相关制度并评估风险等级）"

    input_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string"
            },
            "top_k": {
                "type": "integer"
            },
        },
        "required": ["query"],
    }


    def execute(
            self,
            *,
            query: str,
            user_context: dict | None = None,
            top_k: int = 5
    ) -> dict:

        # 延迟导入，避免模块加载循环依赖
        from work_agent.core.container import rag_service

        meta = rag_service.search_with_meta(
            query,
            top_k=top_k,
            user_context=user_context,
        )

        return {
            "knowledge": meta["results"],
            "candidates": meta["candidates"],
            "denied": meta["denied"],
            "risk_level": self._assess_risk(query),
        }


    @staticmethod
    def _assess_risk(query: str) -> str:

        """
        规则风险评估
        """

        for keyword in HIGH_RISK_KEYWORDS:

            if keyword in query:
                return "high"

        for keyword in MEDIUM_RISK_KEYWORDS:

            if keyword in query:
                return "medium"

        return "low"
