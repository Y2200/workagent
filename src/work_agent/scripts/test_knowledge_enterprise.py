"""
Enterprise Knowledge Agent 测试（Phase 10：制度+用户+组织三源）

Part 1  is_permission_query（权限类问题判定）
Part 2  build_user_profile（用户画像，角色/部门/权限）
Part 3  KnowledgeAgent 权限类问题链路（mock LLM，验证 prompt 含用户画像）

用法：
    python -m work_agent.scripts.test_knowledge_enterprise
"""

# 副作用：触发 config.py stdout UTF-8 重配置（Windows GBK）
import work_agent.config  # noqa: F401

from work_agent.agent.context import AgentContext
from work_agent.agent.organization import (
    build_user_profile,
    is_permission_query,
)


def _ctx(
        username="员工A",
        department="财务部",
        role="员工",
        permissions=None,
        role_codes=None,
):
    return AgentContext(
        request_id="test-knowledge",
        tenant_id="1",
        user_id=2,
        username=username,
        department=department,
        role=role,
        permissions=set(permissions or []),
        role_codes=set(role_codes or []),
    )


def test_p1_permission_query():
    """Part 1：权限类问题判定"""
    assert is_permission_query("我能不能申请远程办公")
    assert is_permission_query("我有权限查看客户合同吗")
    assert is_permission_query("员工是否可以申请报销")
    assert is_permission_query("允许我提交这个流程吗")

    assert not is_permission_query("财务报销标准是什么")
    assert not is_permission_query("请假流程怎么走")
    assert not is_permission_query("")
    print("✓ Part1 权限类问题判定")


def test_p2_user_profile():
    """Part 2：用户画像构建"""
    # 普通员工
    emp = _ctx(
        permissions={"document:view", "task:view", "task:submit", "policy:view"},
        role_codes={"USER"},
    )
    profile = build_user_profile(emp)
    assert "员工A" in profile
    assert "财务部" in profile
    assert "普通员工" in profile
    assert "提交任务" in profile
    print("  员工画像:", profile.replace("\n", " | "))

    # 部门经理
    mgr = _ctx(
        username="王经理",
        department="研发部",
        role="管理员",
        permissions={"task:create", "task:view_employee", "task:remind",
                     "email:send", "policy:view", "task:view"},
        role_codes={"DEPARTMENT_ADMIN"},
    )
    profile_mgr = build_user_profile(mgr)
    assert "部门经理" in profile_mgr
    assert "发布任务" in profile_mgr
    assert "查看员工任务" in profile_mgr
    print("  经理画像:", profile_mgr.replace("\n", " | "))

    print("✓ Part2 用户画像")


def test_p3_knowledge_agent_profile():
    """Part 3：KnowledgeAgent 权限类问题 → prompt 含用户画像"""
    from work_agent.agent.agents.knowledge_agent import KnowledgeAgent

    captured = {}

    class _FakeTool:
        def execute(self, **kwargs):
            return {
                "results": [
                    {"text": "远程办公制度：普通员工需部门经理审批",
                     "source": "远程办公制度.md", "score": 0.9},
                ],
                "denied": False,
                "candidates": 1,
            }

    class _FakeLLM:
        def invoke(self, prompt, **kwargs):
            captured["prompt"] = prompt
            class _R:
                content = "根据制度，您作为普通员工可以申请远程办公，但需部门经理审批。"
            return _R()

    agent = KnowledgeAgent(
        knowledge_tool=_FakeTool(),
        query_rewriter=None,
    )
    agent.llm = _FakeLLM()

    from work_agent.agent.schemas import PlanResult, PlanStep, IntentType

    plan = PlanResult(
        kind="knowledge",
        intent=IntentType.POLICY_QUERY,
        steps=[
            PlanStep(step_id=1, tool="knowledge_tool", action="search"),
        ],
    )

    result = agent.run(
        context=_ctx(
            permissions={"document:view", "policy:view", "task:view"},
            role_codes={"USER"},
        ),
        plan=plan,
        message="我能不能申请远程办公",
    )

    # prompt 应包含用户画像
    prompt = captured["prompt"]
    assert "姓名：员工A" in prompt, "prompt 应含用户画像"
    assert "普通员工" in prompt, "prompt 应含角色"
    assert result.response, "应有回复"
    assert "远程办公" in result.response, result.response
    print("✓ Part3 KnowledgeAgent 权限类问题结合用户画像")


def test_p4_non_permission_no_profile():
    """Part 4：非权限类问题不追加画像"""
    from work_agent.agent.agents.knowledge_agent import KnowledgeAgent

    captured = {}

    class _FakeTool:
        def execute(self, **kwargs):
            return {
                "results": [
                    {"text": "财务报销制度：员工差旅标准", "source": "报销.md", "score": 0.9},
                ],
                "denied": False,
                "candidates": 1,
            }

    class _FakeLLM:
        def invoke(self, prompt, **kwargs):
            captured["prompt"] = prompt
            class _R:
                content = "根据制度回答。"
            return _R()

    agent = KnowledgeAgent(
        knowledge_tool=_FakeTool(),
        query_rewriter=None,
    )
    agent.llm = _FakeLLM()

    from work_agent.agent.schemas import PlanResult, PlanStep, IntentType

    plan = PlanResult(
        kind="knowledge",
        intent=IntentType.POLICY_QUERY,
        steps=[
            PlanStep(step_id=1, tool="knowledge_tool", action="search"),
        ],
    )

    agent.run(
        context=_ctx(permissions={"document:view", "policy:view"}, role_codes={"USER"}),
        plan=plan,
        message="财务报销标准是什么",
    )

    # 非权限类问题：user_profile 为"无"
    assert "无，非权限类问题" in captured["prompt"], captured["prompt"][:100]
    print("✓ Part4 非权限类问题不追加画像")


def test():
    print("== Enterprise Knowledge Agent 测试 ==")
    test_p1_permission_query()
    test_p2_user_profile()
    test_p3_knowledge_agent_profile()
    test_p4_non_permission_no_profile()
    print("Enterprise Knowledge 测试全部通过")


if __name__ == "__main__":
    test()
