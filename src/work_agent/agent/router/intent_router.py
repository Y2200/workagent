import json
import re

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
        IntentType.TASK_MANAGEMENT: ("task_tool", True),
        IntentType.TASK_CREATE: ("task_tool", True),
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

        # 任务上下文优先：消息匹配员工任务名 → 直接任务意图（不进 LLM）
        task_match = self._match_task_context(
            message,
            user_context,
        )

        if task_match:

            return IntentResult(
                intent=IntentType.TASK_MANAGEMENT,
                confidence=0.95,
                need_tool=True,
                tool="task_tool",
                entities={
                    "action": "detail",
                    "task_title": task_match,
                },
                reasoning="任务上下文匹配",
            )

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

            result = self._validate(
                data
            )

            # 短确认/取消词 → 强制任务确认动作（LLM 无状态，无法感知 pending）
            override = self._task_override(
                message
            )

            if override:

                return override

            return result

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


    @staticmethod
    def _match_task_context(
            message: str,
            user_context: dict | None
    ) -> str | None:

        """
        任务上下文匹配：短消息命中用户任务名 → 返回任务标题

        仅限短消息（≤16 字符），避免覆盖长句提交/查询
        """

        if not user_context:

            return None

        user_id = user_context.get(
            "user_id"
        )

        tenant_id = (
            user_context.get(
                "tenant_id",
                "",
            )
            or ""
        )

        if not user_id or not tenant_id:

            return None

        try:

            from work_agent.services.task_service import task_service

            task = task_service.resolve_task_from_message(
                tenant_id=tenant_id,
                employee_id=user_id,
                message=message,
            )

            return task.title if task else None

        except Exception:

            return None

    @staticmethod
    def _task_override(
            message: str
    ) -> IntentResult | None:

        """
        短确认/取消词（如员工回复「确认」）→ 强制任务确认动作

        仅限短消息，避免覆盖「确认提交XX任务 完成50%」这类提交消息
        """

        msg = message.strip()

        if len(msg) > 10:

            return None

        if msg in ("确认", "确定") or msg.startswith("确认"):

            return IntentResult(
                intent=IntentType.TASK_MANAGEMENT,
                confidence=0.9,
                need_tool=True,
                tool="task_tool",
                entities={"action": "confirm"},
                reasoning="确认指令",
            )

        if msg in ("取消",) or msg.startswith("取消"):

            return IntentResult(
                intent=IntentType.TASK_MANAGEMENT,
                confidence=0.9,
                need_tool=True,
                tool="task_tool",
                entities={"action": "cancel"},
                reasoning="取消指令",
            )

        return None


    @staticmethod
    def _task_action_entities(
            msg: str
    ) -> dict:

        """
        规则回退时推断任务动作
        """

        if "确认" in msg:

            return {"action": "confirm"}

        if "取消" in msg:

            return {"action": "cancel"}

        if "提交" in msg or "进度" in msg:

            return {"action": "submit"}

        if "完成" in msg:

            return {"action": "complete"}

        if "部门任务" in msg or "部门情况" in msg:

            return {"action": "department_tasks"}

        return {"action": "list"}


    def _fallback(
            self,
            message: str
    ) -> IntentResult:

        """
        规则回退（LLM 不可用时保证主流程不阻断）
        """

        msg = message.strip()

        # 任务发布：安排/给XX + 任务
        if (
            ("安排" in msg or "发布" in msg or "分派" in msg or "指派" in msg)
            and "任务" in msg
        ) or (
            re.match(r"^(给|让)", msg)
            and "任务" in msg
        ):

            return IntentResult(
                intent=IntentType.TASK_CREATE,
                confidence=0.6,
                need_tool=True,
                tool="task_tool",
                entities={"action": "create"},
                reasoning="规则回退：命中任务发布关键词",
            )

        task_keywords = [
            "我的任务",
            "查看任务",
            "任务进度",
            "提交进度",
            "提交任务",
            "任务完成",
            "确认提交",
            "确认",
            "取消",
            "完成任务",
        ]

        if any(
                keyword in msg
                for keyword in task_keywords
        ):

            return IntentResult(
                intent=IntentType.TASK_MANAGEMENT,
                confidence=0.6,
                need_tool=True,
                tool="task_tool",
                entities=self._task_action_entities(msg),
                reasoning="规则回退：命中任务关键词",
            )

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
