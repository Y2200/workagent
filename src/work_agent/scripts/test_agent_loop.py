"""
受约束 Agent Loop 测试（推理 → 执行 → 观察 → 再推理 + 运行保护 Guardrails）

核心循环（场景 1-9）：
1. 多跳：LLM 依据观察提议第二步工具并执行（真·再推理）
2. 简单查询终止：LLM 直接回答 → 仅 1 次工具（成本等价）
3. max_steps 上限：硬停 → 确定性兜底
4. 白名单拒绝：非白名单提议（document_tool.delete）被拒，写操作绝不执行
5. 权限拒绝观察：检索 denied → 立即停，零 LLM 调用
6. 逐步 Policy：循环中某步被策略拒绝 → 中途返回
7. Runtime 集成：完整 execute 走循环（supervisor 不参与）
8. 关闭开关回退 supervisor（零回归）
9. 单跳门控：无多跳信号不进循环（成本不变保证）

运行保护 Guardrails（场景 10-14）：
10. 连续空结果熔断：RAG 查不到 → 2 次后停止，不再反复重试
11. RAG 质量门控：最高检索分低于 min_similarity → 视为无有效知识停止
12. Token 预算熔断：累计 token 超限 → 兜底
13. 时间熔断：超时 → 兜底
14. 重复调用检测：同一 (tool,action,query) 不执行第二次

依赖注入（确定性，不消耗真实 LLM token）：
- AgentLoop(llm=FakeLLM)：脚本化决策
- AgentLoop(config_service=FakeConfig)：agent.loop.* 配置
- AgentLoop(policy_service=FakePolicy)：逐步 Policy 校验
- AgentLoop(usage_callback=FakeCallback)：token 预算熔断验证

兜底为确定性文案（防幻觉）：有观察→罗列已检索内容；无观察→请补充关键词。

用法：
    python -m work_agent.scripts.test_agent_loop
"""

import time

from work_agent.agent.agents.schemas import AgentResult
from work_agent.agent.context import AgentContext
from work_agent.agent.loop import AgentLoop
from work_agent.agent.policy import PolicyDecision
from work_agent.agent.runtime import AgentRuntime
from work_agent.agent.schemas import IntentResult, PlanResult, PlanStep
from work_agent.core.container import document_service
from work_agent.db.models import Conversation
from work_agent.db.session import SessionLocal
from work_agent.repositories.document_repository import DocumentRepository
from work_agent.repositories.user_repository import UserRepository
from work_agent.scripts.seed_tenants import seed_tenants
from work_agent.services.rbac_service import RBACService


# 共享知识文档（覆盖报销/请假/考勤/日报，供检索非空）
_SHARED_DOC_TEXT = (
    "企业综合管理制度：差旅报销需提交发票并经审批；"
    "请假需提前申请并经审批；考勤需每日打卡；日报需按时提交。"
)


# ======================
# 测试替身
# ======================

class _FakeResult:

    def __init__(self, content: str):

        self.content = content


class _FakeLLM:

    """
    脚本化决策 LLM：按顺序返回响应，耗尽后返回兜底回答
    """

    def __init__(self, *responses: str):

        self._responses = list(responses)

        self.calls: list[str] = []


    def invoke(self, prompt, config=None):

        self.calls.append(prompt)

        content = (
            self._responses.pop(0)
            if self._responses
            else '{"kind": "answer", "response": "（FakeLLM 兜底回答）"}'
        )

        return _FakeResult(content)


class _FakeConfig:

    """
    配置中心替身（agent.loop.* 等 key）
    """

    def __init__(self, values=None):

        self.values = values or {}


    def get(self, key: str, tenant_id: str = ""):

        return self.values.get(key)


class _FakePolicy:

    """
    策略替身：analysis_tool 步骤一律拒绝，其余放行
    """

    def evaluate(self, *, intent, plan, context):

        for step in plan.steps:

            if step.tool == "analysis_tool":

                return PolicyDecision(
                    allowed=False,
                    message="无权限执行分析",
                    redirect="可尝试其他方式",
                )

        return PolicyDecision(allowed=True)


class _FakeCallback:

    """
    固定高 total 的 token 回调（触发预算熔断）
    """

    total = 9999


class _FakeSupervisor:

    def __init__(self):

        self.calls = 0


    def dispatch(self, *, context, plan, message):

        self.calls += 1

        return AgentResult(
            agent="fake_supervisor",
            response="supervisor-path",
            intent=plan.intent,
            tools_called=["fake_tool"],
            tool_calls=[{"tool": "fake_tool", "action": "noop"}],
        )


class _StubRouter:

    last_prompt_version = "test-v0"

    def route(self, message, user_context=None, tenant_context=None):

        return IntentResult(
            intent="policy_query",
            confidence=1.0,
            entities={},
            need_tool=True,
            tool="knowledge_tool",
            reasoning="stub",
        )


class _StubPlanner:

    def plan(self, *, message, intent_result, context):

        return PlanResult(
            kind="knowledge",
            intent="policy_query",
            steps=[
                PlanStep(
                    step_id=1,
                    tool="knowledge_tool",
                    action="search",
                    args={"top_k": 5},
                    description="检索企业知识库",
                ),
            ],
            reasoning="stub",
        )


# ======================
# 测试辅助
# ======================

def _cleanup():

    from work_agent.scripts.test_utils import cleanup_tenant_data

    cleanup_tenant_data()

    db = SessionLocal()

    try:

        db.query(Conversation).delete(synchronize_session=False)

        db.commit()

    finally:

        db.close()

    _purge_milvus()


def _purge_milvus() -> int:

    """
    清空 Milvus 全量向量（含空租户残留——cleanup_tenant_data 只清租户 1/2）

    场景10 的「空结果熔断」需要真正的空集合；历史测试留下的空租户孤儿向量
    会让检索非空，导致熔断测试无法触发。
    """

    from work_agent.core.container import rag_service

    store = rag_service.store

    result = store.client.query(
        collection_name=store.COLLECTION_NAME,
        filter="id >= 0",
        output_fields=["id"],
        limit=16384,
        consistency_level="Strong",
    )

    ids = [
        row["id"]
        for row in result
    ]

    if ids:

        store.client.delete(
            collection_name=store.COLLECTION_NAME,
            ids=ids,
            consistency_level="Strong",
        )

        store.client.flush(
            store.COLLECTION_NAME
        )

    return len(ids)


def _user(username: str):

    db = SessionLocal()

    try:

        return UserRepository().get_by_username(db, username)

    finally:

        db.close()


def _ctx(user) -> AgentContext:

    db = SessionLocal()

    try:

        permissions = RBACService().get_permission_codes(db, user.id)

        role_codes = RBACService().get_role_codes(db, user.id)

    finally:

        db.close()

    return AgentContext.build(
        user=user,
        permissions=permissions,
        role_codes=role_codes,
    )


def _knowledge_plan() -> PlanResult:

    return PlanResult(
        kind="knowledge",
        intent="policy_query",
        steps=[
            PlanStep(
                step_id=1,
                tool="knowledge_tool",
                action="search",
                args={"top_k": 5},
                description="检索企业知识库",
            ),
        ],
        reasoning="测试：知识查询",
    )


def _wait_ready(doc_id: int, timeout: float = 60.0):

    db = SessionLocal()

    try:

        start = time.time()

        while time.time() - start < timeout:

            db.expire_all()

            doc = DocumentRepository().get_by_id(db, doc_id)

            if doc and doc.status in ("ready", "failed"):
                return doc.status

            time.sleep(1)

        return "timeout"

    finally:

        db.close()


def _upload_shared(user, tenant_id: str):

    doc = document_service.upload(
        filename="企业综合管理制度.md",
        data=_SHARED_DOC_TEXT.encode("utf-8"),
        category="综合管理",
        uploader=user.username,
        tenant_id=tenant_id,
        visibility="public",
    )

    assert _wait_ready(doc.id) == "ready", doc.id

    return doc.id


# ======================
# 场景
# ======================

def test():

    seed_tenants()

    _cleanup()

    user_a = _user("员工A")

    assert user_a is not None, "需要 员工A（seed_tenants 创建）"

    # ======================
    # 场景5：权限拒绝观察 → 立即停（干净态：仅受限文档存在）
    # ======================

    doc_restr = document_service.upload(
        filename="财务报销制度.md",
        data="财务报销制度：差旅报销需提交发票。".encode("utf-8"),
        category="财务管理",
        uploader=user_a.username,
        tenant_id=user_a.tenant_id,
        visibility="restricted",
        departments=["财务部"],
        roles=["财务人员"],
    )

    assert _wait_ready(doc_restr.id) == "ready", "受限文档应处理就绪"

    user_dev = _user("A研发员工")

    llm5 = _FakeLLM()

    result5 = AgentLoop(llm=llm5).run(
        context=_ctx(user_dev),
        plan=_knowledge_plan(),
        message="财务报销制度是什么",
    )

    assert result5.permission_denied is True, result5

    assert result5.tools_called == ["knowledge_tool"], result5.tools_called

    assert result5.loop_steps == 1, result5.loop_steps

    assert len(llm5.calls) == 0, "权限拒绝后不应再调用 LLM 自主迭代"

    print("场景5 ✅ 权限拒绝观察：立即停，denied 返回，零 LLM 调用")

    document_service.delete(doc_restr.id, tenant_id=user_a.tenant_id)

    # ======================
    # 场景10：Guardrail 连续空结果熔断（干净态：无文档 → 检索全空）
    # ======================

    llm10 = _FakeLLM(
        '{"kind":"tool","step":{"tool":"knowledge_tool","action":"search","args":{"query":"换个词"},"description":"重试"}}',
    )

    result10 = AgentLoop(llm=llm10).run(
        context=_ctx(user_a),
        plan=_knowledge_plan(),
        message="对比报销和请假制度",
    )

    assert result10.tools_called == ["knowledge_tool", "knowledge_tool"], result10.tools_called

    assert result10.loop_steps == 2, result10.loop_steps

    assert result10.response.startswith("当前知识库未检索到足够依据"), result10.response

    assert "补充关键词" in result10.response, result10.response

    print("场景10 ✅ 连续空结果熔断：2 次空检索后停止，返回确定性兜底（不反复重试）")

    # ======================
    # 准备：共享综合管理制度文档（后续场景检索非空）
    # ======================

    _upload_shared(user_a, user_a.tenant_id)

    # ======================
    # 场景1：多跳（真·再推理）——LLM 依据观察提议第二步工具
    # ======================

    llm = _FakeLLM(
        '{"kind":"tool","step":{"tool":"knowledge_tool","action":"search",'
        '"args":{"query":"请假制度"},"description":"补查请假制度"}}',
        '{"kind":"answer","response":"对比结果：报销按A流程，请假按B流程。"}',
    )

    result = AgentLoop(llm=llm).run(
        context=_ctx(user_a),
        plan=_knowledge_plan(),
        message="对比报销制度和请假制度",
    )

    assert result.tools_called == ["knowledge_tool", "knowledge_tool"], result.tools_called

    assert result.loop_steps == 2, result.loop_steps

    assert result.response == "对比结果：报销按A流程，请假按B流程。", result.response

    assert result.permission_denied is False

    print("场景1 ✅ 多跳：2 次工具执行，LLM 依据观察提议第二步，最终回答=LLM 收尾")

    # ======================
    # 场景2：简单查询直接回答（成本等价：1 工具 + 1 LLM）
    # ======================

    llm2 = _FakeLLM(
        '{"kind":"answer","response":"直接回答报销制度。"}',
    )

    result2 = AgentLoop(llm=llm2).run(
        context=_ctx(user_a),
        plan=_knowledge_plan(),
        message="报销制度是什么",
    )

    assert result2.tools_called == ["knowledge_tool"], result2.tools_called

    assert result2.loop_steps == 1, result2.loop_steps

    assert result2.response == "直接回答报销制度。", result2.response

    assert len(llm2.calls) == 1, f"简单查询应只 1 次 LLM 调用（成本等价），实际 {len(llm2.calls)}"

    print("场景2 ✅ 简单查询终止：1 工具 + 1 LLM，成本与现状等价")

    # ======================
    # 场景3：Guardrail max_steps 上限（硬停 → 确定性兜底）
    # ======================

    llm3 = _FakeLLM(
        '{"kind":"tool","step":{"tool":"knowledge_tool","action":"search","args":{"query":"Q1"},"description":"继续"}}',
        '{"kind":"tool","step":{"tool":"knowledge_tool","action":"search","args":{"query":"Q2"},"description":"继续"}}',
    )

    result3 = AgentLoop(
        llm=llm3,
        config_service=_FakeConfig({"agent.loop.max_steps": 2}),
    ).run(
        context=_ctx(user_a),
        plan=_knowledge_plan(),
        message="对比报销和请假制度",
    )

    assert result3.tools_called == ["knowledge_tool", "knowledge_tool"], result3.tools_called

    assert result3.loop_steps == 2, result3.loop_steps

    assert "达到最大执行步数" in result3.response, result3.response

    assert "已检索到以下相关内容" in result3.response, result3.response

    print("场景3 ✅ max_steps 上限：2 步硬停，确定性兜底（引用已检索内容，不生成）")

    # ======================
    # 场景4：工具白名单拒绝（非白名单提议 → 安全兜底，写操作绝不执行）
    # ======================

    llm4 = _FakeLLM(
        '{"kind":"tool","step":{"tool":"document_tool","action":"delete","args":{},"description":"删除文档"}}',
    )

    result4 = AgentLoop(llm=llm4).run(
        context=_ctx(user_a),
        plan=_knowledge_plan(),
        message="查询后帮我删掉文档",
    )

    assert result4.tools_called == ["knowledge_tool"], result4.tools_called

    assert "document_tool" not in result4.tools_called, "写操作绝不允许进入循环"

    # 确定性兜底（有观察→罗列内容；无观察→请补充关键词），非 LLM 自由发挥
    assert (
        "已检索到以下相关内容" in result4.response
        or result4.response.startswith("当前知识库未检索到足够依据")
    ), result4.response

    print("场景4 ✅ 白名单拒绝：document_tool.delete 提议被拒，未执行任何写操作")

    # ======================
    # 场景6：逐步 Policy —— 循环中某步被策略拒绝
    # ======================

    llm6 = _FakeLLM(
        '{"kind":"tool","step":{"tool":"analysis_tool","action":"analyze",'
        '"args":{"query":"风险"},"description":"执行风险分析"}}',
    )

    result6 = AgentLoop(
        llm=llm6,
        policy_service=_FakePolicy(),
    ).run(
        context=_ctx(user_a),
        plan=_knowledge_plan(),
        message="查制度后分析风险",
    )

    assert result6.permission_denied is True, result6

    assert "无权限执行分析" in result6.response, result6.response

    assert "analysis_tool" not in result6.tools_called, "被拒步骤不应执行"

    print("场景6 ✅ 逐步 Policy：analysis_tool 步骤在策略层被拒，未执行")

    # ======================
    # 场景11：Guardrail RAG 质量门控（最高分低于阈值 → 无有效知识）
    # ======================

    llm11 = _FakeLLM()

    result11 = AgentLoop(
        llm=llm11,
        config_service=_FakeConfig({"agent.loop.min_similarity": 1.5}),
    ).run(
        context=_ctx(user_a),
        plan=_knowledge_plan(),
        message="对比报销和请假制度",
    )

    assert result11.tools_called == ["knowledge_tool"], result11.tools_called

    assert "相似度低于质量阈值" in result11.response, result11.response

    assert len(llm11.calls) == 0, "质量门控触发后不应再调用 LLM"

    print("场景11 ✅ RAG 质量门控：最高分 < min_similarity → 停止，判定无有效知识")

    # ======================
    # 场景12：Guardrail Token 预算熔断
    # ======================

    llm12 = _FakeLLM()

    result12 = AgentLoop(
        llm=llm12,
        config_service=_FakeConfig({"agent.loop.max_tokens_budget": 100}),
        usage_callback=_FakeCallback(),
    ).run(
        context=_ctx(user_a),
        plan=_knowledge_plan(),
        message="对比报销和请假制度",
    )

    assert result12.tools_called == ["knowledge_tool"], result12.tools_called

    assert "超出预算或超时" in result12.response, result12.response

    assert len(llm12.calls) == 0, "预算熔断后不应再调用 LLM"

    print("场景12 ✅ Token 预算熔断：累计 token 超限 → 兜底，不再调用 LLM")

    # ======================
    # 场景13：Guardrail 时间熔断
    # ======================

    llm13 = _FakeLLM()

    result13 = AgentLoop(
        llm=llm13,
        config_service=_FakeConfig({"agent.loop.max_duration_seconds": 1e-6}),
    ).run(
        context=_ctx(user_a),
        plan=_knowledge_plan(),
        message="对比报销和请假制度",
    )

    assert result13.tools_called == ["knowledge_tool"], result13.tools_called

    assert "超出预算或超时" in result13.response, result13.response

    print("场景13 ✅ 时间熔断：超时 → 兜底")

    # ======================
    # 场景14：Guardrail 重复调用检测
    # ======================

    llm14 = _FakeLLM(
        '{"kind":"tool","step":{"tool":"knowledge_tool","action":"search","args":{"query":"综合制度"},"description":"再查"}}',
        '{"kind":"tool","step":{"tool":"knowledge_tool","action":"search","args":{"query":"综合制度"},"description":"重复"}}',
    )

    result14 = AgentLoop(llm=llm14).run(
        context=_ctx(user_a),
        plan=_knowledge_plan(),
        message="对比报销和请假制度",
    )

    assert result14.tools_called == ["knowledge_tool", "knowledge_tool"], result14.tools_called

    assert result14.loop_steps == 2, result14.loop_steps

    assert "重复工具调用" in result14.response, result14.response

    print("场景14 ✅ 重复调用检测：同一检索词第二次提议被拒，停止")

    # ======================
    # 场景7：Runtime 集成 —— 循环开启走 loop（supervisor 不参与）
    # ======================

    supervisor = _FakeSupervisor()

    llm7 = _FakeLLM(
        '{"kind":"tool","step":{"tool":"knowledge_tool","action":"search","args":{"query":"补充"},"description":"补充查询"}}',
        '{"kind":"answer","response":"循环集成回答。"}',
    )

    runtime = AgentRuntime(
        intent_router=_StubRouter(),
        planner=_StubPlanner(),
        supervisor=supervisor,
        loop=AgentLoop(llm=llm7),
    )

    r7 = runtime.execute(
        message="对比报销制度和请假制度",
        user=user_a,
        channel="wechat",
    )

    assert supervisor.calls == 0, "循环开启时 supervisor 不应参与"

    assert r7["tools_called"] == ["knowledge_tool", "knowledge_tool"], r7["tools_called"]

    assert r7["loop_steps"] == 2, r7["loop_steps"]

    assert r7["response"] == "循环集成回答。", r7["response"]

    print("场景7 ✅ Runtime 集成：循环开启走 AgentLoop（supervisor.calls==0，2 步）")

    # ======================
    # 场景8：关闭开关回退 supervisor（零回归）
    # ======================

    supervisor8 = _FakeSupervisor()

    runtime8 = AgentRuntime(
        intent_router=_StubRouter(),
        planner=_StubPlanner(),
        supervisor=supervisor8,
        loop=AgentLoop(
            config_service=_FakeConfig({"agent.loop.enabled": False}),
        ),
    )

    r8 = runtime8.execute(
        message="对比报销制度和请假制度",
        user=user_a,
        channel="wechat",
    )

    assert supervisor8.calls == 1, "关闭时 supervisor 应被调用"

    assert r8["agent"] == "fake_supervisor", r8["agent"]

    assert r8["response"] == "supervisor-path", r8["response"]

    print("场景8 ✅ 关闭开关：回退 supervisor 单步路径（零回归）")

    # ======================
    # 场景9：单跳信号不进循环（成本不变保证——门控在消息信号）
    # ======================

    supervisor9 = _FakeSupervisor()

    # 该 LLM 一旦被调用即失败：若单跳查询进了循环，会触发失败
    class _ExplodeLLM:

        def invoke(self, prompt, config=None):

            raise AssertionError("单跳查询不应进入循环（零 LLM 调用）")

    runtime9 = AgentRuntime(
        intent_router=_StubRouter(),
        planner=_StubPlanner(),
        supervisor=supervisor9,
        loop=AgentLoop(llm=_ExplodeLLM()),
    )

    r9 = runtime9.execute(
        message="报销制度是什么",
        user=user_a,
        channel="wechat",
    )

    assert supervisor9.calls == 1, "单跳查询应走 supervisor（不进循环）"

    assert r9["agent"] == "fake_supervisor", r9["agent"]

    assert r9["loop_steps"] is None, r9["loop_steps"]

    print("场景9 ✅ 单跳门控：'报销制度是什么' 不进循环 → 单步路径（成本不变）")

    _cleanup()

    print("Agent Loop 测试全部通过（14 场景：核心循环 9 + Guardrails 5）")


if __name__ == "__main__":

    test()
