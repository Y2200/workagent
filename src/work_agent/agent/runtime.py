"""
Agent Runtime

统一执行管道：

用户请求 → Context Builder → Intent Router → Planner → Tool Executor
        → Response Generator → Audit Logger

wechat/service.py 不再承担 Agent 编排，只负责微信协议/身份解析。
"""

import time

from uuid import uuid4

from work_agent.agent.agents.supervisor import supervisor_agent
from work_agent.agent.context import AgentContext
from work_agent.agent.planner import agent_planner
from work_agent.agent.router.intent_router import IntentRouter
from work_agent.agent.tools.registry import tool_registry
from work_agent.config import settings
from work_agent.core.audit_logger import audit_logger
from work_agent.core.trace import tracer
from work_agent.db.session import SessionLocal
from work_agent.services.conversation_service import conversation_service
from work_agent.services.rbac_service import RBACService


class AgentRuntime:

    """
    可扩展 Agent 执行器

    管道：Context → Intent → Planner → Supervisor → Agent → Tool → Audit
    """

    def __init__(
            self,
            intent_router: IntentRouter | None = None,
            supervisor=None,
            planner=None,
            config_service=None
    ):

        self.intent_router = intent_router or IntentRouter()

        self.supervisor = supervisor or supervisor_agent

        self.planner = planner or agent_planner

        self.config_service = config_service


    def execute(
            self,
            *,
            message: str,
            user,
            channel: str = "wechat"
    ) -> dict:

        """
        执行一次 Agent 请求

        返回：
        {
            "response": str,
            "intent": str,
            "knowledge_sources": list,
            "permission_denied": bool,
            "token_usage": int,
            "request_id": str,
        }
        """

        started = time.monotonic()

        # 统一 request_id：追踪 / 审计 / 会话对齐
        request_id = str(uuid4())

        # 追踪：开启（纯增量，失败静默）
        tracer.start(
            request_id=request_id,
            tenant_id=user.tenant_id,
            user_id=user.id,
            channel=channel,
        )

        trace_status = "ok"

        trace_error_type = ""

        trace_error_message = ""

        # ======================
        # Context Builder（含 RBAC 权限解析）
        # ======================

        with tracer.span("context_builder", component="context_builder"):

            db = SessionLocal()

            try:

                permissions = RBACService().get_permission_codes(
                    db,
                    user.id
                )

            finally:

                db.close()

            # 会话管理：同一 (租户, 用户, 渠道) 复用会话
            conversation_id = conversation_service.get_or_create(
                tenant_id=user.tenant_id,
                user_id=user.id,
                channel=channel,
            )

            context = AgentContext.build(
                user=user,
                channel=channel,
                permissions=permissions,
                conversation_id=str(conversation_id),
                model_name=settings.model_name,
                agent_version=settings.agent_version,
                request_id=request_id,
            )

        # ======================
        # LLM 成本治理：预算拦截（在调用 LLM 之前）
        # ======================

        quota = self._check_quota(context)

        if quota is not None and not quota["allowed"]:

            return self._budget_blocked(
                context=context,
                channel=channel,
                message=message,
                budget=quota,
                started=started,
            )

        # ======================
        # Intent Router
        # ======================

        with tracer.span("intent_router", component="intent_router"):

            intent_result = self.intent_router.route(
                message,
                user_context=context.to_user_context(),
                tenant_context={
                    "tenant_id": context.tenant_id,
                },
            )

            context.prompt_version = (
                self.intent_router.last_prompt_version
            )

            tracer.add_attributes(
                intent=intent_result.intent,
                confidence=intent_result.confidence,
            )

        # ======================
        # Audit：记录开始
        # ======================

        ctx = audit_logger.log_request(
            request_id=context.request_id,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            department=context.department,
            role=context.role,
            channel=channel,
            question=message,
            agent_version=context.agent_version,
            model_name=context.model_name,
        )

        try:

            # ======================
            # Planner：生成执行计划
            # ======================

            with tracer.span("planner", component="planner"):

                plan = self.planner.plan(
                    message=message,
                    intent_result=intent_result,
                    context=context,
                )

                tracer.add_attributes(
                    plan_kind=plan.kind,
                    steps=len(plan.steps),
                )

            # ======================
            # 配置中心：工具停用拦截（不执行 Agent）
            # ======================

            disabled = self._disabled_tools(
                context,
                plan,
            )

            # ======================
            # Supervisor → 专业 Agent → Tool
            # ======================

            with tracer.span("supervisor", component="supervisor"):

                if disabled:

                    # 治理拦截：配置中心停用工具，返回明确消息
                    result = {
                        "response": (
                            "相关工具已停用："
                            + "、".join(disabled)
                            + "，请联系管理员。"
                        ),
                        "permission_denied": False,
                        "token_usage": 0,
                        "knowledge_sources": [],
                        "agent": "config_center",
                        "plan_kind": plan.kind,
                        "tools_called": [],
                        "tool_calls": [],
                    }

                else:

                    agent_result = self.supervisor.dispatch(
                        context=context,
                        plan=plan,
                        message=message,
                    )

                    result = agent_result.to_dict()

                    # 评测观测字段（additive）
                    result["agent"] = agent_result.agent

                    result["plan_kind"] = plan.kind

                # intent 统一用 Intent Router 的分类（legacy 路径不覆盖）
                result["intent"] = intent_result.intent

                tracer.add_attributes(
                    agent=result.get(
                        "agent",
                        "",
                    ),
                    plan_kind=plan.kind,
                    tools=result.get(
                        "tools_called",
                        [],
                    ),
                )

            latency_ms = (
                time.monotonic() - started
            ) * 1000

            denied = bool(
                result.get(
                    "permission_denied"
                )
            )

            # ======================
            # Audit：记录完成
            # ======================

            with tracer.span("audit", component="audit"):

                audit_logger.log_success(
                    ctx,
                    answer=result.get(
                        "response",
                        ""
                    ),
                    intent=result.get(
                        "intent",
                        ""
                    ),
                    retrieval_documents=result.get(
                        "knowledge_sources",
                        []
                    ),
                    status=(
                        "denied"
                        if denied
                        else "success"
                    ),
                    latency_ms=latency_ms,
                    token_usage=result.get(
                        "token_usage",
                        0
                    ),
                    prompt_version=context.prompt_version,
                    intent_confidence=intent_result.confidence,
                    tools_called=result.get(
                        "tools_called",
                        [],
                    ),
                )

                # LLM 成本记账（失败静默）
                self._record_cost(
                    context,
                    result,
                )

                # 记录会话活动
                try:

                    conversation_service.touch(
                        int(context.conversation_id),
                    )

                except Exception:
                    pass

            result["request_id"] = context.request_id

            result["conversation_id"] = context.conversation_id

            return result

        except Exception as exc:

            # ======================
            # Audit：记录失败
            # ======================

            trace_status = "error"

            trace_error_type = type(exc).__name__

            trace_error_message = str(exc)

            latency_ms = (
                time.monotonic() - started
            ) * 1000

            audit_logger.log_error(
                ctx,
                error_type=trace_error_type,
                error_message=trace_error_message,
                latency_ms=latency_ms,
            )

            raise

        finally:

            # 追踪收尾（写库单事务，失败静默）
            tracer.finish(
                status=trace_status,
                error_type=trace_error_type,
                error_message=trace_error_message,
            )


    def _disabled_tools(
            self,
            context,
            plan
    ) -> list[str]:

        """
        配置中心停用的工具列表（agent.tools.enabled）

        未设置 = 全部启用
        """

        config_service = self._get_config_service()

        if config_service is None:
            return []

        enabled = config_service.get(
            "agent.tools.enabled",
            context.tenant_id,
        )

        if enabled is None or not isinstance(enabled, list):
            return []

        enabled_set = set(enabled)

        return [
            step.tool
            for step in (plan.steps or [])
            if step.tool and step.tool not in enabled_set
        ]


    def _get_config_service(self):

        if self.config_service is None:

            # 延迟导入，避免容器初始化循环依赖
            from work_agent.core.container import agent_config_service

            self.config_service = agent_config_service

        return self.config_service


    # ======================
    # LLM 成本治理
    # ======================

    def _check_quota(self, context):

        """
        校验租户预算额度；成本服务不可用时返回 None（放行）
        """

        cost_service = self._get_cost_service()

        if cost_service is None:
            return None

        try:

            return cost_service.check_quota(
                context.tenant_id,
            )

        except Exception:

            return None


    def _budget_blocked(
            self,
            *,
            context,
            channel: str,
            message: str,
            budget: dict,
            started: float
    ) -> dict:

        """
        预算超限：记录 denied 审计并返回优雅消息（不调用 LLM）
        """

        ctx = audit_logger.log_request(
            request_id=context.request_id,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            department=context.department,
            role=context.role,
            channel=channel,
            question=message,
            agent_version=context.agent_version,
            model_name=context.model_name,
        )

        audit_logger.log_error(
            ctx,
            status="denied",
            error_type="budget_exceeded",
            error_message=(
                f"月度预算已用完"
                f"（{budget.get('spent')}/{budget.get('budget')}）"
            ),
            latency_ms=(
                time.monotonic() - started
            ) * 1000,
        )

        tracer.finish(status="ok")

        return {
            "response": (
                "本月 LLM 预算已用完，"
                "请联系管理员调整预算后再使用。"
            ),
            "intent": "",
            "permission_denied": False,
            "token_usage": 0,
            "knowledge_sources": [],
            "agent": "cost_center",
            "plan_kind": "",
            "tools_called": [],
            "request_id": context.request_id,
            "conversation_id": context.conversation_id,
        }


    def _record_cost(
            self,
            context,
            result: dict
    ) -> None:

        """
        记账本次执行的 LLM 成本（失败静默）
        """

        tokens = int(
            result.get("token_usage", 0) or 0
        )

        if tokens <= 0:
            return

        cost_service = self._get_cost_service()

        if cost_service is None:
            return

        try:

            cost_service.record(
                tenant_id=context.tenant_id,
                request_id=context.request_id,
                user_id=context.user_id,
                model=context.model_name,
                total_tokens=tokens,
            )

        except Exception:
            pass


    def _get_cost_service(self):

        try:

            from work_agent.core.container import cost_governance_service

            return cost_governance_service

        except Exception:

            return None


# 全局单例
agent_runtime = AgentRuntime()
