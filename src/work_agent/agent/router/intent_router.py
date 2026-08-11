import json

from work_agent.agent.llm import get_llm
from work_agent.agent.schemas import IntentResult, IntentType
from work_agent.core.prompt_manager import prompt_manager
from work_agent.core.utils import parse_json


class IntentRouter:

    """
    LLM 意图路由

    输入：message + user_context + tenant_context
    输出：结构化 IntentResult

    LLM 失败时回退到规则判断（不阻断主流程）
    """

    # 意图 → (默认工具, 是否需要工具)
    INTENT_TOOL_MAP = {
        IntentType.KNOWLEDGE_QUERY: ("knowledge_tool", True),
        IntentType.DOCUMENT_OPERATION: ("document_tool", True),
        IntentType.AUDIT_QUERY: ("audit_tool", True),
        IntentType.WORKFLOW_REQUEST: ("", False),
        IntentType.RISK_ANALYSIS: ("", False),
        IntentType.SMALL_TALK: ("", False),
        IntentType.UNKNOWN: ("", False),
    }

    # 置信度低于该值视为未知
    CONFIDENCE_THRESHOLD = 0.5

    def __init__(
            self,
            llm=None
    ):

        self.llm = llm or get_llm()

        # 最近一次使用的 Prompt 版本（供审计）
        self.last_prompt_version = ""


    def route(
            self,
            message: str,
            user_context: dict | None = None,
            tenant_context: dict | None = None
    ) -> IntentResult:

        """
        意图路由
        """

        try:

            loaded = prompt_manager.load(
                "intent_router"
            )

            self.last_prompt_version = loaded["version"]

            prompt = loaded["content"].format(
                message=message,
                user_context=json.dumps(
                    user_context or {},
                    ensure_ascii=False,
                ),
                tenant_context=json.dumps(
                    tenant_context or {},
                    ensure_ascii=False,
                ),
            )

            result = self.llm.invoke(
                prompt
            )

            data = parse_json(
                result.content
            )

            return self._validate(
                data
            )

        except Exception:

            # LLM 异常/输出非法 → 规则回退
            return self._fallback(
                message
            )


    def _validate(
            self,
            data: dict
    ) -> IntentResult:

        """
        校验并规整 LLM 输出
        """

        intent = data.get(
            "intent",
            IntentType.UNKNOWN
        )

        if intent not in self.INTENT_TOOL_MAP:
            intent = IntentType.UNKNOWN

        try:
            confidence = float(
                data.get(
                    "confidence",
                    0.0
                )
            )
        except (TypeError, ValueError):
            confidence = 0.0

        confidence = min(
            max(confidence, 0.0),
            1.0
        )

        # 按意图强制工具映射，防止 LLM 输出与意图不一致
        default_tool, default_need = self.INTENT_TOOL_MAP[intent]

        need_tool = bool(
            data.get(
                "need_tool",
                default_need
            )
        )

        tool = data.get(
            "tool",
            default_tool
        )

        if intent != IntentType.UNKNOWN:

            if not tool or not need_tool:

                tool = default_tool

                need_tool = default_need

        result = IntentResult(
            intent=intent,
            confidence=confidence,
            entities=data.get(
                "entities",
                {}
            ) or {},
            need_tool=need_tool,
            tool=tool,
            reasoning=data.get(
                "reasoning",
                ""
            ),
        )

        # 置信度过低 → 视为未知
        if confidence < self.CONFIDENCE_THRESHOLD:

            result.intent = IntentType.UNKNOWN

            result.need_tool = False

            result.tool = ""

        return result


    def _fallback(
            self,
            message: str
    ) -> IntentResult:

        """
        规则回退（LLM 不可用时保证主流程不阻断）
        """

        msg = message.strip()

        knowledge_keywords = [
            "制度",
            "政策",
            "流程",
            "规定",
            "是什么",
            "怎么做",
            "如何",
            "怎么",
            "报销",
            "请假",
            "审批",
            "提交",
        ]

        risk_keywords = [
            "延期",
            "未提交",
            "忘记",
            "事故",
            "风险",
            "异常",
            "超期",
        ]

        if any(
                keyword in msg
                for keyword in knowledge_keywords
        ):

            return IntentResult(
                intent=IntentType.KNOWLEDGE_QUERY,
                confidence=0.6,
                need_tool=True,
                tool="knowledge_tool",
                reasoning="规则回退：命中知识查询关键词",
            )

        if any(
                keyword in msg
                for keyword in risk_keywords
        ):

            return IntentResult(
                intent=IntentType.RISK_ANALYSIS,
                confidence=0.6,
                reasoning="规则回退：命中风险关键词",
            )

        if len(msg) < 3:

            return IntentResult(
                intent=IntentType.SMALL_TALK,
                confidence=0.5,
                reasoning="规则回退：短消息",
            )

        return IntentResult(
            intent=IntentType.UNKNOWN,
            confidence=0.3,
            reasoning="规则回退：无法识别",
        )
