"""
Agent 多步执行现状测试（坐实 plan.steps[1:] 被丢弃）

背景：
planner.plan_with_llm 有能力返回多步 PlanStep 列表，但当前执行链路
Runtime → Supervisor → 专业 Agent（operation_agent/knowledge_agent/analysis_agent）
都只消费 plan.steps[0]，后续步骤被静默丢弃。

本测试坐实该行为（三个层面）：
- 场景1（Agent 级，确定性，无 LLM）：构造 2 步计划
  （document_tool.list → audit_tool.logs），执行 operation_agent，
  断言只有步骤1的工具被调用（tools_called == ["document_tool"]），
  步骤2 的 audit_tool 从未执行。
- 场景2（Runtime 级）：用 stub intent_router + stub planner 返回 2 步文档计划，
  走完整 runtime.execute，断言工具调用详情只含步骤1，步骤2 未执行。
- 场景3（Policy 层对照）：policy.evaluate 会遍历全部 plan.steps 做权限校验
  （Policy 层已是 loop-ready），截断发生在执行器，不在策略层。

边界说明（有意为之）：
- document 多步计划仍为单步执行——document_operation 是写/管理类意图，
  **不进受约束 Agent Loop**（只读意图才可循环），保持单步 + 用户确认流。
- 知识/风险意图的多步执行能力由「受约束 Agent Loop」提供
  （agent/loop.py，agent.loop.enabled 默认开启），见 scripts/test_agent_loop.py。

用途：
- 记录 document 意图的执行边界（本测试通过 = 截断仍存在，是设计边界非缺陷）

用法：
    python -m work_agent.scripts.test_step_execution
"""

import time

from work_agent.agent.agents.registry import agent_registry
from work_agent.agent.context import AgentContext
from work_agent.agent.runtime import AgentRuntime
from work_agent.agent.schemas import IntentResult, PlanResult, PlanStep
from work_agent.core.container import document_service
from work_agent.db.models import Conversation
from work_agent.db.session import SessionLocal
from work_agent.repositories.document_repository import DocumentRepository
from work_agent.repositories.user_repository import UserRepository
from work_agent.scripts.seed_tenants import seed_tenants
from work_agent.services.rbac_service import RBACService


def _cleanup():

    from work_agent.scripts.test_utils import cleanup_tenant_data

    cleanup_tenant_data()

    db = SessionLocal()

    try:

        db.query(Conversation).delete(synchronize_session=False)

        db.commit()

    finally:

        db.close()


def _user(username: str):

    db = SessionLocal()

    try:

        return UserRepository().get_by_username(db, username)

    finally:

        db.close()


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


def _admin_context(admin_a) -> AgentContext:

    db = SessionLocal()

    try:

        permissions = RBACService().get_permission_codes(db, admin_a.id)

        role_codes = RBACService().get_role_codes(db, admin_a.id)

    finally:

        db.close()

    return AgentContext.build(
        user=admin_a,
        permissions=permissions,
        role_codes=role_codes,
    )


def _multi_step_plan() -> PlanResult:

    """
    2 步计划：步骤1 查文档，步骤2 查审计日志
    """

    return PlanResult(
        kind="document",
        intent="document_operation",
        steps=[
            PlanStep(
                step_id=1,
                tool="document_tool",
                action="list",
                args={},
                description="查看知识库文档列表",
            ),
            PlanStep(
                step_id=2,
                tool="audit_tool",
                action="logs",
                args={"page_size": 5},
                description="查看问答审计日志",
            ),
        ],
        reasoning="测试：多步计划",
    )


def test():

    seed_tenants()

    _cleanup()

    admin_a = _user("admin_A")

    assert admin_a is not None, "需要 admin_A（seed_tenants 创建）"

    # 上传一个内存文档，让场景1的文档列表非空（不依赖 knowledge/ 目录）
    doc = document_service.upload(
        filename="测试制度.md",
        data="测试制度内容：这是一个用于多步执行测试的制度文档。".encode("utf-8"),
        category="测试",
        uploader=admin_a.username,
        tenant_id=admin_a.tenant_id,
        visibility="public",
    )

    assert _wait_ready(doc.id) == "ready", "测试文档应处理就绪"

    # ======================
    # 场景1：Agent 级截断（确定性，无 LLM）
    # ======================

    ctx = _admin_context(admin_a)

    op_agent = agent_registry.get("operation_agent")

    assert op_agent is not None

    result = op_agent.run(
        context=ctx,
        plan=_multi_step_plan(),
        message="查看知识库文档和审计日志",
    )

    # 只有步骤1 的工具被执行
    assert result.tools_called == ["document_tool"], (
        f"截断未发生？实际调用 {result.tools_called}"
    )

    # 响应里只有文档列表，没有任何审计日志内容
    assert "测试制度.md" in result.response, result.response

    assert "问答审计" not in result.response, (
        "步骤2（audit_tool）被错误执行，不应出现在响应中"
    )

    print("场景1 ✅ Agent 级：2 步计划只执行 steps[0]（document_tool），steps[1:] 被丢弃")

    # ======================
    # 场景2：Runtime 级截断（stub router + stub planner，走完整 execute）
    # ======================

    class _StubRouter:

        last_prompt_version = "test-v0"

        def route(
                self,
                message,
                user_context=None,
                tenant_context=None,
        ) -> IntentResult:

            return IntentResult(
                intent="document_operation",
                confidence=1.0,
                entities={},
                need_tool=True,
                tool="document_tool",
                reasoning="stub",
            )

    class _StubPlanner:

        def plan(
                self,
                *,
                message,
                intent_result,
                context,
        ) -> PlanResult:

            return _multi_step_plan()

    runtime = AgentRuntime(
        intent_router=_StubRouter(),
        planner=_StubPlanner(),
    )

    r = runtime.execute(
        message="查看知识库文档和审计日志",
        user=admin_a,
        channel="wechat",
    )

    assert r["tools_called"] == ["document_tool"], (
        f"Runtime 级未截断？实际 tools_called={r['tools_called']}"
    )

    assert "audit_tool" not in r["tools_called"], (
        "步骤2（audit_tool）被错误执行"
    )

    assert "测试制度.md" in r["response"], r["response"]

    print("场景2 ✅ Runtime 级：完整 execute 也只执行 steps[0]，步骤2 未执行")

    # ======================
    # 场景3：Policy 层确实遍历全部步骤（loop-ready 证据）
    # ======================

    from dataclasses import replace

    from work_agent.agent.policy import policy_service

    decision = policy_service.evaluate(
        intent="document_operation",
        plan=_multi_step_plan(),
        context=ctx,
    )

    assert decision.allowed is True, (
        f"Policy 应放行（admin 全权限），实际 {decision}"
    )

    # 反向证明：构造一个步骤2 需要 audit:view 的权限缺失场景
    restricted_ctx = replace(ctx, permissions={"document:view"})

    denied = policy_service.evaluate(
        intent="document_operation",
        plan=_multi_step_plan(),
        context=restricted_ctx,
    )

    assert denied.allowed is False, (
        "缺少 audit:view 时应被 Policy 拒绝（证明 Policy 遍历了步骤2）"
    )

    print("场景3 ✅ Policy 层遍历全部步骤（步骤2 缺权限被拒）→ 截断不在策略层")

    document_service.delete(doc.id, tenant_id=admin_a.tenant_id)

    _cleanup()

    print("Step Execution 测试全部通过（坐实：执行器只消费 steps[0]）")


if __name__ == "__main__":

    test()
