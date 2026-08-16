"""
企业任务决策层（Policy Decision Layer）测试（Phase 7A）

场景：
- 员工发布任务 → 拒绝
- 经理发布任务 → 放行
- 员工查自己的任务 → 放行
- 员工查员工任务 → 拒绝（无 task:view_employee）
- 经理查员工任务 → 放行
- 员工提交进度 → 放行
- 经理提交进度 → 拒绝（无 task:submit）
- confirm 双用途（submit ∨ create）
- policy:view 等价 document:view（旧库兼容）
- System Agent 权限检查（system:scan 通过 / 普通权限拒绝）
- 无步骤（chat）→ 放行

用法：
    python -m work_agent.scripts.test_policy
"""

# 副作用：触发 config.py stdout UTF-8 重配置（Windows GBK）
import work_agent.config  # noqa: F401

from work_agent.agent.context import AgentContext
from work_agent.agent.policy import policy_service
from work_agent.agent.schemas import IntentType, PlanResult, PlanStep


def _ctx(
        permissions: set[str] | None = None,
        role_codes: set[str] | None = None,
        is_system: bool = False,
):
    return AgentContext(
        request_id="test-policy",
        tenant_id="1",
        user_id=1,
        username="tester",
        department="研发部",
        role="员工",
        permissions=set(permissions or []),
        role_codes=set(role_codes or []),
        is_system=is_system,
    )


def _plan(tool: str, action: str, intent: str):
    return PlanResult(
        kind="task",
        intent=intent,
        steps=[
            PlanStep(
                step_id=1,
                tool=tool,
                action=action,
            ),
        ],
    )


def _allowed(intent, tool, action, ctx):
    decision = policy_service.evaluate(
        intent=intent,
        plan=_plan(tool, action, intent),
        context=ctx,
    )
    return decision.allowed, decision


def test_employee_create_denied():
    """员工发布任务 → 拒绝"""
    emp = _ctx(
        permissions={"task:view", "task:submit", "policy:view"},
        role_codes={"USER"},
    )
    allowed, decision = _allowed(
        IntentType.CREATE_TASK, "task_tool", "create", emp,
    )
    assert not allowed, decision
    assert decision.message == "无 task:create 权限", decision.message
    assert "发布任务权限" in decision.redirect, decision.redirect
    print("✓ 员工发布任务 → 拒绝 + 重定向")


def test_manager_create_allowed():
    """经理发布任务 → 放行"""
    mgr = _ctx(
        permissions={"task:view", "task:create", "task:view_employee",
                     "task:remind", "email:send", "policy:view"},
        role_codes={"DEPARTMENT_ADMIN"},
    )
    allowed, _ = _allowed(IntentType.CREATE_TASK, "task_tool", "create", mgr)
    assert allowed
    print("✓ 经理发布任务 → 放行")


def test_employee_query_my_allowed():
    """员工查自己的任务 → 放行"""
    emp = _ctx(
        permissions={"task:view", "task:submit", "policy:view"},
        role_codes={"USER"},
    )
    allowed, _ = _allowed(IntentType.QUERY_MY_TASK, "task_tool", "list", emp)
    assert allowed
    print("✓ 员工查自己的任务 → 放行")


def test_employee_query_employee_denied():
    """员工查员工任务 → 拒绝（无 view_employee + 非管理角色）"""
    emp = _ctx(
        permissions={"task:view", "task:submit", "policy:view"},
        role_codes={"USER"},
    )
    allowed, decision = _allowed(
        IntentType.QUERY_EMPLOYEE_TASK, "task_tool", "employee_tasks", emp,
    )
    assert not allowed, decision
    print("✓ 员工查员工任务 → 拒绝")


def test_manager_query_employee_allowed():
    """经理查员工任务 → 放行"""
    mgr = _ctx(
        permissions={"task:view", "task:view_employee"},
        role_codes={"DEPARTMENT_ADMIN"},
    )
    allowed, _ = _allowed(
        IntentType.QUERY_EMPLOYEE_TASK, "task_tool", "employee_tasks", mgr,
    )
    assert allowed
    print("✓ 经理查员工任务 → 放行")


def test_employee_submit_allowed():
    """员工提交进度 → 放行"""
    emp = _ctx(
        permissions={"task:view", "task:submit", "policy:view"},
        role_codes={"USER"},
    )
    allowed, _ = _allowed(IntentType.SUBMIT_TASK, "task_tool", "submit", emp)
    assert allowed
    print("✓ 员工提交进度 → 放行")


def test_manager_submit_denied():
    """经理提交进度 → 拒绝（DEPARTMENT_ADMIN 无 task:submit）"""
    mgr = _ctx(
        permissions={"task:view", "task:create", "task:view_employee"},
        role_codes={"DEPARTMENT_ADMIN"},
    )
    allowed, _ = _allowed(IntentType.SUBMIT_TASK, "task_tool", "submit", mgr)
    assert not allowed
    print("✓ 经理提交进度 → 拒绝")


def test_confirm_dual_permission():
    """confirm 双用途：员工(submit) 或 经理(create) 任一可确认"""
    # 员工确认进度（有 submit）
    emp = _ctx(
        permissions={"task:view", "task:submit"},
        role_codes={"USER"},
    )
    allowed, _ = _allowed(IntentType.SUBMIT_TASK, "task_tool", "confirm", emp)
    assert allowed

    # 经理确认创建（有 create，无 submit）
    mgr = _ctx(
        permissions={"task:view", "task:create"},
        role_codes={"DEPARTMENT_ADMIN"},
    )
    allowed2, _ = _allowed(IntentType.CREATE_TASK, "task_tool", "confirm", mgr)
    assert allowed2

    # 无 submit 无 create → 拒绝
    nobody = _ctx(
        permissions={"task:view"},
        role_codes={"USER"},
    )
    allowed3, _ = _allowed(IntentType.SUBMIT_TASK, "task_tool", "confirm", nobody)
    assert not allowed3

    print("✓ confirm 双用途（submit ∨ create）")


def test_policy_equivalent_document():
    """policy:view 等价 document:view（旧库 USER 兼容）"""
    # 旧库 USER 只有 document:view（未重刷 seed_rbac）
    old_user = _ctx(
        permissions={"document:view", "task:view"},
        role_codes={"USER"},
    )
    allowed, _ = _allowed(IntentType.POLICY_QUERY, "knowledge_tool", "search", old_user)
    assert allowed
    print("✓ policy:view 等价 document:view")


def test_system_permission_check():
    """System Agent 权限检查：system:scan 通过 / 普通权限拒绝"""
    # 有 system:scan
    sys_ok = _ctx(
        permissions={"system:scan"},
        role_codes=set(),
        is_system=True,
    )
    decision = policy_service.evaluate(
        intent="system_scan",
        plan=_plan("reminder_service", "scan", "system_scan"),
        context=sys_ok,
    )
    assert decision.allowed, decision

    # is_system 但无 system 权限 → 拒绝（不直接放行）
    sys_bad = _ctx(
        permissions={"task:create"},
        role_codes=set(),
        is_system=True,
    )
    decision2 = policy_service.evaluate(
        intent="system_scan",
        plan=_plan("reminder_service", "scan", "system_scan"),
        context=sys_bad,
    )
    assert not decision2.allowed, decision2
    print("✓ System Agent 权限检查（不直接放行）")


def test_chat_no_steps_allowed():
    """无步骤（chat/legacy/unknown）→ 放行"""
    ctx = _ctx(
        permissions=set(),
        role_codes={"USER"},
    )
    plan = PlanResult(kind="chat", intent=IntentType.SMALL_TALK, steps=[])
    decision = policy_service.evaluate(
        intent=IntentType.SMALL_TALK,
        plan=plan,
        context=ctx,
    )
    assert decision.allowed
    print("✓ 无步骤（chat）→ 放行")


def test():
    print("== 企业任务决策层（Policy）测试 ==")
    test_employee_create_denied()
    test_manager_create_allowed()
    test_employee_query_my_allowed()
    test_employee_query_employee_denied()
    test_manager_query_employee_allowed()
    test_employee_submit_allowed()
    test_manager_submit_denied()
    test_confirm_dual_permission()
    test_policy_equivalent_document()
    test_system_permission_check()
    test_chat_no_steps_allowed()
    print("Policy 测试全部通过")


if __name__ == "__main__":
    test()
