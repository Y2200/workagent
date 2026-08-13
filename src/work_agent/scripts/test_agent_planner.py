"""
Agent Planner 测试（P5-1）

验证：
- 知识查询 → knowledge 计划（knowledge_tool 步骤）
- 文档操作 → document 计划（对应工具步骤）
- 督导/风险 → legacy 计划
- LLM 规划（plan_with_llm）
- Runtime 集成（按计划执行）

用法：
    python -m work_agent.scripts.test_agent_planner
"""

from work_agent.agent.context import AgentContext
from work_agent.agent.planner import agent_planner
from work_agent.agent.router.intent_router import IntentRouter
from work_agent.agent.schemas import IntentType
from work_agent.db.session import SessionLocal
from work_agent.repositories.user_repository import UserRepository
from work_agent.scripts.seed_tenants import seed_tenants


def test():

    seed_tenants()

    db = SessionLocal()

    try:

        admin = UserRepository().get_by_username(db, "admin_A")

    finally:

        db.close()

    context = AgentContext.build(
        user=admin,
        channel="wechat",
    )

    router = IntentRouter()

    # ======================
    # 场景1：知识查询 → knowledge 计划
    # ======================

    intent1 = router.route(
        "财务报销制度是什么",
        user_context=context.to_user_context(),
        tenant_context={"tenant_id": context.tenant_id},
    )

    assert intent1.intent == IntentType.KNOWLEDGE_QUERY, intent1.intent

    plan1 = agent_planner.plan(
        message="财务报销制度是什么",
        intent_result=intent1,
        context=context,
    )

    assert plan1.kind == "knowledge", plan1.kind

    assert len(plan1.steps) == 1, plan1.steps

    assert plan1.steps[0].tool == "knowledge_tool", plan1.steps[0]

    print(f"场景1 ✅ 知识查询 → knowledge 计划: {plan1.steps[0].tool}")

    # ======================
    # 场景2：文档操作 → document 计划
    # ======================

    intent2 = router.route(
        "删除文档5",
        user_context=context.to_user_context(),
        tenant_context={"tenant_id": context.tenant_id},
    )

    assert intent2.intent == IntentType.DOCUMENT_OPERATION, intent2.intent

    plan2 = agent_planner.plan(
        message="删除文档5",
        intent_result=intent2,
        context=context,
    )

    assert plan2.kind == "document", plan2.kind

    assert plan2.steps[0].tool == "document_tool", plan2.steps

    assert plan2.steps[0].action == "delete", plan2.steps[0]

    assert plan2.steps[0].args.get("document_id") == 5, plan2.steps[0]

    print(
        f"场景2 ✅ 文档操作 → document 计划: "
        f"{plan2.steps[0].tool}/{plan2.steps[0].action}"
    )

    # ======================
    # 场景3a：风险 → risk 计划（analysis_agent）
    # ======================

    intent3 = router.route(
        "项目延期了3天，有风险",
        user_context=context.to_user_context(),
        tenant_context={"tenant_id": context.tenant_id},
    )

    plan3 = agent_planner.plan(
        message="项目延期了3天，有风险",
        intent_result=intent3,
        context=context,
    )

    assert plan3.kind == "risk", plan3.kind

    assert plan3.steps[0].tool == "analysis_tool", plan3.steps

    print(f"场景3a ✅ 风险 → risk 计划 (intent={intent3.intent})")

    # ======================
    # 场景3b：任务查询 → task 计划（任务督导 Agent 接管）
    # ======================

    intent3b = router.route(
        "我的任务完成了吗",
        user_context=context.to_user_context(),
        tenant_context={"tenant_id": context.tenant_id},
    )

    plan3b = agent_planner.plan(
        message="我的任务完成了吗",
        intent_result=intent3b,
        context=context,
    )

    assert plan3b.kind == "task", plan3b.kind

    assert plan3b.steps[0].tool == "task_tool", plan3b.steps

    print(f"场景3b ✅ 任务查询 → task 计划 (intent={intent3b.intent})")

    # ======================
    # 场景4：LLM 规划（plan_with_llm）
    # ======================

    plan4 = agent_planner.plan_with_llm(
        message="财务报销制度是什么",
        intent_result=intent1,
        context=context,
    )

    assert plan4.kind in ("knowledge", "document"), plan4.kind

    assert plan4.steps, plan4.steps

    print(
        f"场景4 ✅ LLM 规划: kind={plan4.kind}, "
        f"steps={len(plan4.steps)}, prompt_version={agent_planner.last_prompt_version}"
    )

    # ======================
    # 场景5：Runtime 集成（按计划执行知识问答）
    # ======================

    from work_agent.agent.runtime import AgentRuntime

    runtime = AgentRuntime()

    result = runtime.execute(
        message="财务报销制度是什么",
        user=admin,
        channel="wechat",
    )

    assert result["intent"] == IntentType.KNOWLEDGE_QUERY, result["intent"]

    assert result["tools_called"] == ["knowledge_tool"], result["tools_called"]

    assert result["response"], result["response"]

    print(
        f"场景5 ✅ Runtime 按计划执行: tools={result['tools_called']}"
    )

    print("Agent Planner 测试全部通过")


if __name__ == "__main__":

    test()
