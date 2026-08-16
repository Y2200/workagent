"""
System Proactive Agent 测试（Phase 11）

Part 1  build_system_context（is_system=True + system 权限）
Part 2  Policy System Permission Check（system:scan 通过 / 普通权限拒绝 / is_system 不直接放行）
Part 3  run_daily_scan 执行（mock 企微，走 System Agent 链路）

用法：
    python -m work_agent.scripts.test_system_agent
"""

# 副作用：触发 config.py stdout UTF-8 重配置（Windows GBK）
import work_agent.config  # noqa: F401

from work_agent.agent.context import AgentContext
from work_agent.agent.system_agent import (
    SYSTEM_PERMISSIONS,
    build_system_context,
)


def test_p1_system_context():
    """Part 1：build_system_context"""
    ctx = build_system_context(tenant_id="1", department="研发部")

    assert ctx.is_system is True
    assert ctx.username == "system"
    assert ctx.user_id is None
    assert ctx.department == "研发部"
    assert "system:scan" in ctx.permissions
    assert "task:remind" in ctx.permissions
    assert "report:send" in ctx.permissions
    assert ctx.role_codes == set()

    # SYSTEM_PERMISSIONS 定义完整
    assert SYSTEM_PERMISSIONS == {"system:scan", "task:remind", "report:send"}
    print("✓ Part1 build_system_context")


def test_p2_policy_system_check():
    """Part 2：Policy System Permission Check"""
    from work_agent.agent.policy import policy_service
    from work_agent.agent.schemas import PlanResult, PlanStep

    def _plan():
        return PlanResult(
            kind="task",
            intent="system_scan",
            steps=[
                PlanStep(
                    step_id=1,
                    tool="reminder_service",
                    action="scan",
                ),
            ],
        )

    # system:scan 通过
    sys_ok = AgentContext(
        request_id="t",
        tenant_id="1",
        user_id=None,
        username="system",
        department="",
        role="system",
        permissions={"system:scan", "task:remind", "report:send"},
        role_codes=set(),
        is_system=True,
    )
    decision = policy_service.evaluate(
        intent="system_scan",
        plan=_plan(),
        context=sys_ok,
    )
    assert decision.allowed, decision

    # is_system 但无 system 权限 → 拒绝（不直接放行）
    sys_bad = AgentContext(
        request_id="t",
        tenant_id="1",
        user_id=None,
        username="system",
        department="",
        role="system",
        permissions={"task:create"},  # 普通用户权限
        role_codes=set(),
        is_system=True,
    )
    decision2 = policy_service.evaluate(
        intent="system_scan",
        plan=_plan(),
        context=sys_bad,
    )
    assert not decision2.allowed, decision2
    assert "System Agent" in decision2.message, decision2.message

    print("✓ Part2 Policy System Permission Check")


def test_p3_daily_scan():
    """Part 3：run_daily_scan 执行"""
    import work_agent.wechat.client as wc

    class FakeClient:
        def send_text_message(self, user_id, content):
            return {"errcode": 0, "errmsg": "ok"}

    old_client = wc.wecom_client
    wc.wecom_client = FakeClient()

    try:
        from work_agent.agent.system_agent import system_proactive_agent

        result = system_proactive_agent.run_daily_scan(
            tenant_id="1",
            department="研发部",
        )
        assert result["status"] == "done", result
        assert result["agent"] == "system_agent"
        assert result["is_system"] is True
        assert "summary" in result
        assert "scanned" in result["summary"]
        print(f"  daily scan: {result['summary']}")
        print("✓ Part3 run_daily_scan 执行")
    finally:
        wc.wecom_client = old_client


def test():
    print("== System Proactive Agent 测试 ==")
    test_p1_system_context()
    test_p2_policy_system_check()
    test_p3_daily_scan()
    print("System Agent 测试全部通过")


if __name__ == "__main__":
    test()
