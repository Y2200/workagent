"""
受约束 Agent Loop（推理 → 执行 → 观察 → 再推理）

对比请求驱动型单步执行（intent → 1 工具 → 1 回答，LLM 只在两端）：
本循环让 LLM 进入执行中间——每执行一步只读工具，就基于观察结果决定
「下一步工具」或「直接回答」，直到信息足够或触发运行保护（Guardrails）。

生产可控循环（Guardrails，防无限调用 / 成本失控 / 幻觉）：
1. max_steps：最大执行步数（默认 5），防无限循环
2. 连续空结果熔断（max_empty_observations，默认 2）：RAG 查不到就停止，不反复重试
3. Token 预算熔断（max_tokens_budget，默认 8000）：单次 Loop 累计 token 超限强制收尾
4. 时间熔断（max_duration_seconds，默认 15）：企业场景防长尾拖拽
5. RAG 质量门控（min_similarity，默认 0.45）：最高检索分低于阈值视为无有效知识
   （bge 余弦分普遍 0.5-0.7，0.45 只拦明显无关垃圾召回，可按业务调高）
6. 重复调用检测：同一 (tool, action, query) 不执行第二次
7. 确定性兜底（Fallback）：触发保护后返回固定文案（已检索内容 / 未找到依据），
   不让 LLM 基于低质量上下文自由发挥（防幻觉）

约束三件套（企业安全铁律不破）：
- 工具白名单：LLM 只能提议 knowledge_tool / analysis_tool（只读、无副作用）
- 逐步 Policy：每步执行前经 policy_service.evaluate 重校验
- 写操作意图（document/task/notification）永不进入循环（runtime 门控 + 白名单双保险）

agent 上报字段保持「底层能力名」（knowledge_agent/analysis_agent）兼容既有评测断言；
循环是否执行由 loop_steps / tool_calls 长度可观测。
"""

import json
import time

from work_agent.agent.agents.schemas import AgentResult
from work_agent.agent.llm import get_llm
from work_agent.agent.schemas import PlanResult, PlanStep
from work_agent.agent.tools.registry import tool_registry
from work_agent.core.audit_logger import TokenUsageCallback
from work_agent.core.prompt_manager import prompt_manager
from work_agent.core.utils import safe_parse_json


# 循环可处理的计划类型（只读意图）
LOOP_KINDS = {"knowledge", "risk"}

# LLM 可自主提议的下一步工具白名单（只读、query 风格，无副作用）
LOOP_TOOL_WHITELIST = {"knowledge_tool", "analysis_tool"}

# plan.kind → 底层能力名（兼容既有评测 expected_agent 断言）
_CAPABILITY_NAMES = {
    "knowledge": "knowledge_agent",
    "risk": "analysis_agent",
}

# 多跳信号：消息含这些词才启用循环（保证简单查询零成本/零漂移）
# - STRONG：明确要求对比/区别/多个主题
# - OR 并列词：很可能多主题（同一知识/风险意图下出现并列 → 需多次检索）
_MULTI_HOP_STRONG = (
    "对比",
    "比较",
    "区别",
    "差异",
    "异同",
    "分别",
    "两者",
)

_MULTI_HOP_OR = (
    "和",
    "跟",
    "与",
    "同时",
    "以及",
)

# 观察上下文有界：单条观察文本上限 / transcript 总长上限
_SUMMARY_ITEM_CLIP = 500
_TRANSCRIPT_CLIP = 4000

# 兜底文案（防幻觉：保护触发后不让 LLM 自由发挥）
_FALLBACK_NO_INFO = (
    "当前知识库未检索到足够依据，"
    "无法确认相关制度内容，请补充关键词或联系管理员。"
)

# 无检索结果的观察摘要占位（transcript 渲染用）
_NO_RESULT_MARKER = "（未检索到相关制度）"


def is_multi_hop(message: str) -> bool:

    """
    确定性多跳信号判断

    用途：运行时路由门控——只有多主题/对比类知识查询才进入受约束 Agent Loop，
    单一主题查询保持单步执行（成本不变、回答零漂移、既有测试契约不破）。
    """

    msg = (message or "").strip()

    if not msg:

        return False

    if any(
        s in msg
        for s in _MULTI_HOP_STRONG
    ):

        return True

    return any(
        s in msg
        for s in _MULTI_HOP_OR
    )


class AgentLoop:

    """
    受约束 Agent Loop 执行器（含 Guardrails）

    管道：确定性种子步 → 逐步 Policy → 执行工具 → 观察 → 质量/预算/超时检查
          → LLM 再推理（下一步工具 / 直接回答）→ 重复检测 → ... → 兜底

    依赖注入（便于测试确定性）：
    - llm：循环决策 LLM（缺省 get_llm()）
    - policy_service：逐步 Policy 校验（缺省全局 policy_service）
    - config_service：配置中心（agent.loop.* / agent.tools.enabled）
    - tool_whitelist：可提议工具白名单
    - usage_callback：Token 统计回调（缺省内部 TokenUsageCallback；测试可注入以验证预算熔断）
    """

    def __init__(
            self,
            llm=None,
            policy_service=None,
            config_service=None,
            tool_whitelist: set | None = None,
            usage_callback=None,
    ):

        self.llm = llm or get_llm()

        self.policy_service = policy_service

        self.config_service = config_service

        self.tool_whitelist = set(
            tool_whitelist
            or LOOP_TOOL_WHITELIST
        )

        self.usage_callback = usage_callback

        self.last_prompt_version = ""


    # ======================
    # 主入口
    # ======================

    def run(
            self,
            *,
            context,
            plan,
            message: str
    ) -> AgentResult:

        """
        执行受约束 Agent Loop（含运行保护），返回结构化结果
        """

        max_steps = self._max_steps(context)

        max_empty = self._max_empty_observations(context)

        max_tokens = self._max_tokens_budget(context)

        max_duration = self._max_duration_seconds(context)

        min_sim = self._min_similarity(context)

        start = time.monotonic()

        callback = (
            self.usage_callback
            if self.usage_callback is not None
            else TokenUsageCallback()
        )

        entries: list[dict] = []          # 观察记录（transcript）
        tools_called: list[str] = []
        tool_calls: list[dict] = []
        sources: list[dict] = []
        call_history: list[str] = []      # Guardrail#6：已执行的 (tool:action:query)
        consecutive_empty = 0             # Guardrail#2：连续空结果计数

        step = (
            plan.steps[0]
            if plan.steps
            else None
        )

        iteration = 0

        while step is not None and iteration < max_steps:

            iteration += 1

            # a. 逐步 Policy（每步执行前重校验）
            decision = self._policy(
                context,
                plan,
                step,
            )

            if not decision.allowed:

                return self._policy_denied(
                    plan,
                    decision,
                    callback,
                    tools_called,
                    tool_calls,
                    sources,
                )

            # b. 工具停用检查（配置中心）
            disabled = self._disabled_tool(
                context,
                step,
            )

            if disabled:

                return AgentResult(
                    agent=self._capability_name(plan),
                    response=(
                        f"相关工具已停用：{disabled}，"
                        "请联系管理员。"
                    ),
                    intent=plan.intent,
                    permission_denied=False,
                    token_usage=callback.total,
                    tools_called=tools_called,
                    tool_calls=tool_calls,
                    knowledge_sources=sources,
                    loop_steps=iteration,
                )

            # c. Guardrail#6：重复调用检测（种子步无重复概念，从第 2 步起）
            if iteration > 1:

                key = self._step_key(step, message)

                if key in call_history:

                    return self._guardrail_fallback(
                        plan,
                        callback,
                        tools_called,
                        tool_calls,
                        sources,
                        entries,
                        "检测到重复工具调用，已停止",
                    )

            # d. 执行工具 → 观察
            is_first = iteration == 1

            obs = self._execute_step(
                context,
                step,
                message,
                is_first,
            )

            call_history.append(
                self._key(
                    obs["tool"],
                    obs["action"],
                    obs.get("query", ""),
                )
            )

            tools_called.append(obs["tool"])

            tool_calls.append(
                {
                    "tool": obs["tool"],
                    "action": obs["action"],
                }
            )

            if obs.get("sources"):

                sources.extend(obs["sources"])

            # e. 权限拒绝观察 → 立即停（不再继续自主迭代）
            if obs.get("denied"):

                return AgentResult(
                    agent=self._capability_name(plan),
                    response="权限不足，无法完成该查询。",
                    intent=plan.intent,
                    permission_denied=True,
                    token_usage=callback.total,
                    tools_called=tools_called,
                    tool_calls=tool_calls,
                    knowledge_sources=sources,
                    loop_steps=iteration,
                )

            # f. 追加观察
            entries.append(
                {
                    "step": iteration,
                    "tool": obs["tool"],
                    "query": obs.get("query", ""),
                    "summary": obs.get("summary", ""),
                }
            )

            # g. Guardrail#2：连续空结果熔断
            if obs.get("empty"):

                consecutive_empty += 1

            else:

                consecutive_empty = 0

            if consecutive_empty >= max_empty:

                return self._guardrail_fallback(
                    plan,
                    callback,
                    tools_called,
                    tool_calls,
                    sources,
                    entries,
                    f"连续 {consecutive_empty} 次未检索到有效结果，已停止",
                )

            # h. Guardrail#5：RAG 质量门控（最高分低于阈值 → 无有效知识）
            best = obs.get("best_score")

            if (
                best is not None
                and min_sim is not None
                and best > 0
                and best < min_sim
            ):

                return self._guardrail_fallback(
                    plan,
                    callback,
                    tools_called,
                    tool_calls,
                    sources,
                    entries,
                    "检索相似度低于质量阈值，已停止",
                )

            # i. Guardrail#3/#4：Token 预算 / 超时（think 前）
            if (
                self._budget_exceeded(callback.total, max_tokens)
                or self._duration_exceeded(start, max_duration)
            ):

                return self._guardrail_fallback(
                    plan,
                    callback,
                    tools_called,
                    tool_calls,
                    sources,
                    entries,
                    "超出预算或超时，已停止",
                )

            # j. LLM 再推理：下一步工具 / 直接回答
            think = self._think(
                context,
                plan,
                message,
                entries,
                max_steps,
                callback,
            )

            # k. Guardrail#3/#4：think 之后复检（LLM 调用已消耗 token/时间）
            if (
                self._budget_exceeded(callback.total, max_tokens)
                or self._duration_exceeded(start, max_duration)
            ):

                return self._guardrail_fallback(
                    plan,
                    callback,
                    tools_called,
                    tool_calls,
                    sources,
                    entries,
                    "超出预算或超时，已停止",
                )

            if think.get("kind") == "answer":

                return AgentResult(
                    agent=self._capability_name(plan),
                    response=(
                        think.get("response")
                        or "好的。"
                    ),
                    intent=plan.intent,
                    knowledge_sources=sources,
                    permission_denied=False,
                    token_usage=callback.total,
                    tools_called=tools_called,
                    tool_calls=tool_calls,
                    loop_steps=iteration,
                )

            next_step = self._proposed_step(think)

            if next_step is None:

                # 无效 / 非白名单提议 → 安全收尾（不再调用任何工具）
                break

            step = next_step

        # Guardrail#1：max_steps 用尽 / 非法提议 → 确定性兜底
        return self._guardrail_fallback(
            plan,
            callback,
            tools_called,
            tool_calls,
            sources,
            entries,
            "达到最大执行步数，已停止",
        )


    # ======================
    # 工具执行（白名单适配）
    # ======================

    def _execute_step(
            self,
            context,
            step,
            message: str,
            is_first: bool
    ) -> dict:

        """
        执行单步工具，返回观察结果 dict（含 quality/empty/best_score 供 Guardrails）
        """

        tool_name = step.tool

        if tool_name == "knowledge_tool":

            top_k = int(
                step.args.get("top_k", 5)
                or 5
            )

            query = (
                self._rewrite_query(message, context)
                if is_first
                else (step.args.get("query") or message)
            )

            return self._execute_knowledge(
                context,
                query,
                top_k,
            )

        if tool_name == "analysis_tool":

            query = (
                step.args.get("query")
                or message
            )

            top_k = int(
                step.args.get("top_k", 5)
                or 5
            )

            return self._execute_analysis(
                context,
                query,
                top_k,
            )

        # 非白名单工具（正常情况下不会到达：逐步 Policy + 提议校验双重拦截）
        return {
            "tool": tool_name,
            "action": step.action,
            "query": "",
            "summary": "",
            "empty": True,
            "best_score": None,
            "denied": False,
            "sources": [],
        }


    def _execute_knowledge(
            self,
            context,
            query: str,
            top_k: int
    ) -> dict:

        tool = tool_registry.get("knowledge_tool")

        res = tool.execute(
            query=query,
            user_context=context.to_user_context(),
            top_k=top_k,
        )

        results = res.get("results", []) or []

        sources = [
            {
                "source": item.get("source", ""),
                "score": item.get("score", 0),
            }
            for item in results
        ]

        scores = [
            item.get("score")
            or 0
            for item in results
        ]

        best_score = (
            max(scores)
            if scores
            else None
        )

        empty = len(results) == 0

        summary = (
            "\n".join(
                f"- {self._clip(item.get('text', ''))}"
                for item in results
            )
            if not empty
            else ""
        )

        return {
            "tool": "knowledge_tool",
            "action": "search",
            "query": query,
            "summary": summary,
            "empty": empty,
            "best_score": best_score,
            "denied": bool(res.get("denied")),
            "sources": sources,
        }


    def _execute_analysis(
            self,
            context,
            query: str,
            top_k: int
    ) -> dict:

        tool = tool_registry.get("analysis_tool")

        res = tool.execute(
            query=query,
            user_context=context.to_user_context(),
            top_k=top_k,
        )

        knowledge = res.get("knowledge", []) or []

        sources = [
            {
                "source": item.get("source", ""),
                "score": item.get("score", 0),
            }
            for item in knowledge
        ]

        scores = [
            item.get("score")
            or 0
            for item in knowledge
        ]

        best_score = (
            max(scores)
            if scores
            else None
        )

        empty = len(knowledge) == 0

        policies = "、".join(
            item.get("source", "")
            for item in knowledge
            if item.get("source")
        )

        summary = (
            (
                f"风险等级：{res.get('risk_level', '')}；"
                f"相关制度：{policies}"
            )
            if not empty
            else ""
        )

        return {
            "tool": "analysis_tool",
            "action": "analyze",
            "query": query,
            "summary": summary,
            "empty": empty,
            "best_score": best_score,
            "denied": bool(res.get("denied")),
            "sources": sources,
        }


    # ======================
    # LLM 再推理
    # ======================

    def _think(
            self,
            context,
            plan,
            message: str,
            entries: list[dict],
            max_steps: int,
            callback
    ) -> dict:

        """
        循环决策：基于观察 → 下一步工具 / 直接回答
        解析失败 / 非白名单提议 → 返回 {}（上层安全收尾）
        """

        try:

            loaded = prompt_manager.load("agent_loop")

            self.last_prompt_version = loaded["version"]

            prompt = loaded["content"].format(
                message=message,
                user_context=json.dumps(
                    context.to_user_context(),
                    ensure_ascii=False,
                ),
                user_profile=self._user_profile(
                    context,
                    message,
                ),
                transcript=self._render_transcript(entries),
                available_tools=json.dumps(
                    self._available_tools(),
                    ensure_ascii=False,
                ),
                max_steps=max_steps,
            )

            result = self.llm.invoke(
                prompt,
                config={
                    "callbacks": [callback],
                }
            )

            data = safe_parse_json(
                result.content,
                default={},
            )

            return data if isinstance(data, dict) else {}

        except Exception:

            return {}


    def _proposed_step(self, think: dict):

        """
        校验 LLM 提议的下一步工具（白名单拦截）
        返回 PlanStep 或 None（拒绝）
        """

        step = think.get("step")

        if not isinstance(step, dict):

            return None

        tool = str(
            step.get("tool")
            or ""
        )

        # 白名单：禁止提议循环外工具（写操作永远无法进入循环）
        if tool not in self.tool_whitelist:

            return None

        args = step.get("args")

        if not isinstance(args, dict):

            args = {}

        return PlanStep(
            step_id=0,
            tool=tool,
            action=str(
                step.get("action")
                or ""
            ),
            args=args,
            description=str(
                step.get("description")
                or ""
            ),
        )


    # ======================
    # 兜底（确定性，防幻觉）
    # ======================

    def _guardrail_fallback(
            self,
            plan,
            callback,
            tools_called,
            tool_calls,
            sources,
            entries,
            reason: str = ""
    ) -> AgentResult:

        """
        运行保护触发后的确定性兜底：
        - 已有有效观察 → 罗列已检索到的相关内容（引用原文，不生成）
        - 无有效观察 → 固定文案（请补充关键词/联系管理员）
        不让 LLM 基于低质量上下文自由发挥（防幻觉）。
        """

        good = list(
            dict.fromkeys(  # 去重（多轮检索可能返回同一文档），保序
                e["summary"]
                for e in entries
                if e.get("summary")
            )
        )

        if good:

            parts = ["已检索到以下相关内容（"] + [reason + "）："]

            parts.append("\n".join(good))

            response = "\n".join(parts)

        else:

            response = _FALLBACK_NO_INFO

        return AgentResult(
            agent=self._capability_name(plan),
            response=response,
            intent=plan.intent,
            knowledge_sources=sources,
            permission_denied=False,
            token_usage=callback.total,
            tools_called=tools_called,
            tool_calls=tool_calls,
            loop_steps=len(tools_called),
        )


    def _policy_denied(
            self,
            plan,
            decision,
            callback,
            tools_called,
            tool_calls,
            sources
    ) -> AgentResult:

        text = (
            decision.message
            or "无权限执行该操作。"
        )

        if decision.redirect:

            text += "\n" + decision.redirect

        return AgentResult(
            agent=self._capability_name(plan),
            response=text,
            intent=plan.intent,
            permission_denied=True,
            token_usage=callback.total,
            tools_called=tools_called,
            tool_calls=tool_calls,
            knowledge_sources=sources,
            loop_steps=len(tools_called),
        )


    # ======================
    # Guardrails：配置读取
    # ======================

    def _max_steps(self, context) -> int:

        return self._cfg_int(
            context,
            "agent.loop.max_steps",
            5,
        )


    def _max_empty_observations(self, context) -> int:

        return self._cfg_int(
            context,
            "agent.loop.max_empty_observations",
            2,
        )


    def _max_tokens_budget(self, context) -> int | None:

        value = self._cfg_int(
            context,
            "agent.loop.max_tokens_budget",
            8000,
        )

        return value if value > 0 else None


    def _max_duration_seconds(self, context) -> float | None:

        config_service = self._get_config_service()

        if config_service:

            try:

                value = config_service.get(
                    "agent.loop.max_duration_seconds",
                    context.tenant_id,
                )

                if isinstance(value, (int, float)) and value > 0:

                    return float(value)

            except Exception:

                pass

        # 实测 DeepSeek 单次调用可达 10-30s，多步循环需留足余量，15s 会误杀正常多步
        return 60.0


    def _min_similarity(self, context) -> float | None:

        config_service = self._get_config_service()

        if config_service:

            try:

                value = config_service.get(
                    "agent.loop.min_similarity",
                    context.tenant_id,
                )

                if isinstance(value, (int, float)) and value > 0:

                    return float(value)

            except Exception:

                pass

        # bge-small-zh 余弦分普遍 0.5-0.7（实测相关文档可低至 0.59），
        # 默认 0.45 只拦明显无关的垃圾召回；如需更严可配置调高
        return 0.45


    def _cfg_int(
            self,
            context,
            key: str,
            default: int
    ) -> int:

        config_service = self._get_config_service()

        if config_service:

            try:

                value = config_service.get(
                    key,
                    context.tenant_id,
                )

                if isinstance(value, int) and value > 0:

                    return value

            except Exception:

                pass

        return default


    def is_enabled(self, context) -> bool:

        """
        循环总开关（agent.loop.enabled，默认 True）
        """

        config_service = self._get_config_service()

        if config_service:

            try:

                value = config_service.get(
                    "agent.loop.enabled",
                    context.tenant_id,
                )

                if isinstance(value, bool):

                    return value

            except Exception:

                pass

        return True


    @staticmethod
    def _budget_exceeded(used: int, max_tokens) -> bool:

        return (
            max_tokens is not None
            and used > max_tokens
        )


    @staticmethod
    def _duration_exceeded(start: float, max_duration) -> bool:

        return (
            max_duration is not None
            and max_duration > 0
            and (time.monotonic() - start) > max_duration
        )


    def _get_config_service(self):

        if self.config_service is None:

            # 延迟导入，避免容器初始化循环依赖
            from work_agent.core.container import (
                agent_config_service,
            )

            self.config_service = agent_config_service

        return self.config_service


    def _get_policy_service(self):

        if self.policy_service is None:

            from work_agent.agent.policy import policy_service

            self.policy_service = policy_service

        return self.policy_service


    # ======================
    # 约束与辅助
    # ======================

    def _policy(self, context, plan, step):

        policy_service = self._get_policy_service()

        single = PlanResult(
            kind=plan.kind,
            intent=plan.intent,
            steps=[step],
        )

        return policy_service.evaluate(
            intent=plan.intent,
            plan=single,
            context=context,
        )


    def _disabled_tool(self, context, step) -> str | None:

        config_service = self._get_config_service()

        if config_service is None:

            return None

        try:

            enabled = config_service.get(
                "agent.tools.enabled",
                context.tenant_id,
            )

        except Exception:

            return None

        if (
            enabled is None
            or not isinstance(enabled, list)
        ):

            return None

        if (
            step.tool
            and step.tool not in set(enabled)
        ):

            return step.tool

        return None


    def _available_tools(self) -> list[dict]:

        """
        提供给循环 LLM 的可调用工具清单（仅白名单）
        """

        return [
            {
                "name": info["name"],
                "description": info.get("description", ""),
                "input_schema": info.get("input_schema", {}),
            }
            for info in tool_registry.list_tools()
            if info["name"] in self.tool_whitelist
        ]


    def _user_profile(self, context, message: str) -> str:

        """
        权限/资格类问题追加用户画像（与 knowledge_agent 行为一致）
        """

        try:

            from work_agent.agent.organization import (
                build_user_profile,
                is_permission_query,
            )

            if is_permission_query(message):

                return build_user_profile(context)

        except Exception:

            pass

        return "（无，非权限类问题）"


    def _rewrite_query(self, message: str, context) -> str:

        """
        首步查询复用会话记忆改写（与 knowledge_agent 行为一致）
        """

        try:

            from work_agent.agent.query_rewriter import query_rewriter

            history = (
                getattr(context, "chat_history", None)
                or []
            )

            return query_rewriter.rewrite_query(
                message,
                history,
            )

        except Exception:

            return message


    def _render_transcript(
            self,
            entries: list[dict]
    ) -> str:

        """
        观察记录渲染（有界：单条观察上限 + 总长上限，防循环 LLM 上下文膨胀）
        """

        if not entries:

            return "（尚无观察结果）"

        lines = []

        for e in entries:

            lines.append(
                f"第{e['step']}步 [{e['tool']}] "
                f"查询「{e.get('query', '')}」："
            )

            lines.append(
                e.get("summary", "")
                or _NO_RESULT_MARKER
            )

        text = "\n".join(lines)

        if len(text) > _TRANSCRIPT_CLIP:

            text = text[:_TRANSCRIPT_CLIP] + "\n…（已截断）"

        return text


    @staticmethod
    def _step_key(step, message: str) -> str:

        """
        Guardrail#6：提议步骤的归一化调用键（tool:action:query）
        """

        query = (
            step.args.get("query")
            or message
        )

        return AgentLoop._key(
            step.tool,
            step.action or "",
            query,
        )


    @staticmethod
    def _key(tool: str, action: str, query: str) -> str:

        return f"{tool}:{action}:{query}"


    @staticmethod
    def _capability_name(plan) -> str:

        return _CAPABILITY_NAMES.get(
            plan.kind,
            "agent_loop",
        )


    @staticmethod
    def _clip(text, max_len: int = _SUMMARY_ITEM_CLIP) -> str:

        text = (text or "").strip()

        if len(text) > max_len:

            return text[:max_len] + "…"

        return text


# 全局单例
agent_loop = AgentLoop()
