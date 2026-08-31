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
    # 企业任务意图拆分（Phase 7A）；兼容别名指向同一值
    INTENT_TOOL_MAP = {
        IntentType.KNOWLEDGE_QUERY: ("knowledge_tool", True),
        IntentType.DOCUMENT_OPERATION: ("document_tool", True),
        IntentType.AUDIT_QUERY: ("audit_tool", True),
        IntentType.WORKFLOW_REQUEST: ("", False),
        IntentType.RISK_ANALYSIS: ("", False),
        IntentType.QUERY_MY_TASK: ("task_tool", True),
        IntentType.QUERY_EMPLOYEE_TASK: ("task_tool", True),
        IntentType.CREATE_TASK: ("task_tool", True),
        IntentType.SUBMIT_TASK: ("task_tool", True),
        IntentType.REMIND_TASK: ("notification_tool", True),
        IntentType.SUMMARY_TASK: ("task_tool", True),
        IntentType.QUERY_DEPARTMENT_MEMBERS: ("user_tool", True),
        IntentType.POLICY_QUERY: ("knowledge_tool", True),
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
                intent=IntentType.QUERY_MY_TASK,
                confidence=0.95,
                need_tool=True,
                tool="task_tool",
                entities={
                    "action": "detail",
                    "task_title": task_match,
                },
                reasoning="任务上下文匹配",
            )

        # 内置命令：查看本部门员工（确定性，先于 LLM / 补充回复，
        # 避免「查看本部门员工」「查看名单」被当员工姓名/任务标题处理）
        member_query = self._member_query_override(
            message,
        )

        if member_query:

            return member_query

        # 任务创建补充回复：在途草稿未完成（缺执行人/任务名）时，
        # 短消息（如补执行人回「张三」）强制路由到 create，使其合并续补
        supplement = self._create_supplement_override(
            message,
            user_context,
        )

        if supplement:

            return supplement

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

            # 指代词追问（"那经理呢？"）→ 强制知识查询（rewrite 在 KnowledgeAgent 处理）
            # LLM 对短追问无状态，无法感知上一轮制度；此处确定性路由到 knowledge
            follow_up = self._follow_up_override(
                message
            )

            if follow_up:

                return follow_up

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

    MEMBER_QUERY_PATTERNS = [
        "查看本部门员工",
        "查看部门员工",
        "查看员工",
        "看员工",
        "查看名单",
        "看名单",
        "查看成员",
        "员工名单",
        "部门名单",
        "部门成员",
        "部门有哪些员工",
        "部门有哪些人",
        "有哪些员工",
        "本部门都有谁",
        "部门都有谁",
        "部门的人",
        "同事名单",
    ]

    @staticmethod
    def _member_query_override(
            message: str
    ) -> IntentResult | None:

        """
        内置命令：查看本部门员工（确定性路由）

        命中「查看本部门员工 / 查看名单 / 查看员工 / 员工名单」等 → 直接走
        user_tool.list_department，不把命令文本当员工姓名/任务标题。
        任务语境（含"任务/进度/完成"）排除，交给任务路由。
        """

        msg = message.strip()

        if not msg:

            return None

        if any(
            kw in msg
            for kw in ("任务", "进度", "完成")
        ):

            return None

        for pattern in IntentRouter.MEMBER_QUERY_PATTERNS:

            if pattern in msg:

                return IntentResult(
                    intent=IntentType.QUERY_DEPARTMENT_MEMBERS,
                    confidence=0.95,
                    need_tool=True,
                    tool="user_tool",
                    entities={"action": "list_department"},
                    reasoning="内置命令：查看本部门员工",
                )

        return None

    @staticmethod
    def _create_supplement_override(
            message: str,
            user_context: dict | None
    ) -> IntentResult | None:

        """
        任务创建补充回复：在途草稿未完成（缺执行人/任务名）时，
        短消息（姓名/任务名，如补执行人回「张三」）强制路由到 create，
        使 preview_create_task 合并续补。

        确认/取消由 _task_override 先行处理（此处排除）。
        """

        msg = message.strip()

        if not msg or len(msg) > 12:

            return None

        # 内置命令（查看本部门员工/名单等）不当作姓名补充
        if IntentRouter._member_query_override(message):

            return None

        if (
            msg in ("确认", "确定")
            or msg.startswith("确认")
        ):

            return None

        if msg in ("取消",) or msg.startswith("取消"):

            return None

        user_id = (user_context or {}).get(
            "user_id",
        )

        if not user_id:

            return None

        try:

            from work_agent.services.task_service import task_service

            if not task_service.has_incomplete_pending_create(
                int(user_id),
            ):

                return None

        except Exception:

            return None

        return IntentResult(
            intent=IntentType.CREATE_TASK,
            confidence=0.9,
            need_tool=True,
            tool="task_tool",
            entities={"action": "create"},
            reasoning="任务创建补充回复（在途草稿缺字段）",
        )

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
                intent=IntentType.SUBMIT_TASK,
                confidence=0.9,
                need_tool=True,
                tool="task_tool",
                entities={"action": "confirm"},
                reasoning="确认指令",
            )

        if msg in ("取消",) or msg.startswith("取消"):

            return IntentResult(
                intent=IntentType.SUBMIT_TASK,
                confidence=0.9,
                need_tool=True,
                tool="task_tool",
                entities={"action": "cancel"},
                reasoning="取消指令",
            )

        return None


    def _follow_up_override(
            self,
            message: str
    ) -> IntentResult | None:

        """
        指代词追问（"那经理呢？""这个制度呢"）→ 强制知识查询

        会话记忆中 rewrite 在 KnowledgeAgent 内处理；但短追问若被 LLM/规则
        路由到其他意图（如 legacy 督导），rewrite 无从执行。此处确定性
        把指代词追问路由到 knowledge_query（KnowledgeAgent 会结合历史改写）。

        排除任务语境（含"任务/进度/完成"→ 可能是任务追问，走原任务逻辑）。
        """

        from work_agent.agent.query_rewriter import QueryRewriter

        msg = message.strip()

        if not msg:
            return None

        # 任务语境追问不覆盖（如"那我的任务呢"）
        if any(
            kw in msg
            for kw in ("任务", "进度", "完成")
        ):
            return None

        if not QueryRewriter._is_follow_up(msg):
            return None

        return IntentResult(
            intent=IntentType.KNOWLEDGE_QUERY,
            confidence=0.7,
            need_tool=True,
            tool="knowledge_tool",
            reasoning="指代词追问：路由到知识查询（rewrite 补全）",
        )


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

        # "完成" 但疑问句（"完成了吗"）是状态查询，非提交完成
        if "完成" in msg and not msg.strip().endswith("吗"):

            return {"action": "complete"}

        if "部门任务" in msg or "部门情况" in msg:

            return {"action": "department_tasks"}

        # 查看指定员工任务（非"我的任务"）
        if (
            re.search(r"(?:查看|查|看).+的\s*任务", msg)
            and "我的任务" not in msg
        ):

            return {"action": "employee_tasks"}

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
                intent=IntentType.CREATE_TASK,
                confidence=0.6,
                need_tool=True,
                tool="task_tool",
                entities={"action": "create"},
                reasoning="规则回退：命中任务发布关键词",
            )

        # 查看指定员工任务（「查看张三的任务」，非"我的任务"）
        if (
            re.search(r"(?:查看|查|看).+的\s*任务", msg)
            and "我的任务" not in msg
        ):

            return IntentResult(
                intent=IntentType.QUERY_EMPLOYEE_TASK,
                confidence=0.6,
                need_tool=True,
                tool="task_tool",
                entities={"action": "employee_tasks"},
                reasoning="规则回退：查看指定员工任务",
            )

        # 主动提醒/督促
        if (
            ("提醒" in msg or "催办" in msg or "督促" in msg)
            and (
                "员工" in msg
                or "同事" in msg
                or "任务" in msg
                or "完成" in msg
            )
        ):

            return IntentResult(
                intent=IntentType.REMIND_TASK,
                confidence=0.6,
                need_tool=True,
                tool="notification_tool",
                entities={"action": "send_wechat"},
                reasoning="规则回退：命中主动提醒关键词",
            )

        # 任务汇总/周报（部门经理/系统）
        if (
            ("周报" in msg or "汇总" in msg or "总结" in msg)
            and "任务" in msg
        ):

            return IntentResult(
                intent=IntentType.SUMMARY_TASK,
                confidence=0.6,
                need_tool=True,
                tool="task_tool",
                entities={"action": "summary"},
                reasoning="规则回退：命中任务汇总关键词",
            )

        # 查看本部门员工（query_department_members，部门经理；排除任务语境）
        if (
            not any(kw in msg for kw in ("任务", "进度"))
            and (
                "本部门员工" in msg
                or "部门员工" in msg
                or "部门成员" in msg
                or "部门有哪些" in msg
                or "有哪些员工" in msg
                or "员工名单" in msg
                or "部门都有谁" in msg
                or "部门的人" in msg
                or "同事名单" in msg
                or "查看员工" in msg
                or "看员工" in msg
                or "查看名单" in msg
                or "看名单" in msg
                or "查看成员" in msg
                or "部门名单" in msg
            )
        ):

            return IntentResult(
                intent=IntentType.QUERY_DEPARTMENT_MEMBERS,
                confidence=0.6,
                need_tool=True,
                tool="user_tool",
                entities={"action": "list_department"},
                reasoning="规则回退：查看本部门员工",
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

        # 泛化提交/完成判断：消息含任务意图动作词（提交/完成/进度/确认）+ 非知识语境
        # 提前拦截，避免被 knowledge 关键词（如"提交"）抢走
        # 排除："我的任务"查询语境 / 疑问句（"完成了吗"是状态查询非提交）
        if (
            ("提交" in msg or "完成" in msg or "进度" in msg)
            and ("任务" in msg or msg.strip() in ("确认", "取消"))
            and "我的任务" not in msg
            and not msg.strip().endswith("吗")
            and not any(kw in msg for kw in ("制度", "政策", "流程", "报销", "请假"))
        ):

            return IntentResult(
                intent=IntentType.SUBMIT_TASK,
                confidence=0.6,
                need_tool=True,
                tool="task_tool",
                entities=self._task_action_entities(msg),
                reasoning="规则回退：命中任务提交/完成关键词",
            )

        if any(
                keyword in msg
                for keyword in task_keywords
        ):

            # 任务关键词：按动作拆 intent（提交类 → SUBMIT_TASK，查看类 → QUERY_MY_TASK）
            action = self._task_action_entities(msg).get(
                "action",
                "list",
            )

            task_intent = (
                IntentType.SUBMIT_TASK
                if action in (
                    "submit",
                    "submit_all",
                    "confirm",
                    "cancel",
                    "complete",
                )
                else IntentType.QUERY_MY_TASK
            )

            return IntentResult(
                intent=task_intent,
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
