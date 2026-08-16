"""
Task Lifecycle 状态机测试（Phase 9）

Part 1  状态机纯函数（合法/非法转移、终态、映射）
Part 2  task_service.transition 集成（超管取消/非法转移/跨租户）
Part 3  Policy 权限（超管可取消/经理拒绝）

用法：
    python -m work_agent.scripts.test_task_flow
"""

# 副作用：触发 config.py stdout UTF-8 重配置（Windows GBK）
import work_agent.config  # noqa: F401

from datetime import datetime, timedelta

from work_agent.agent.task_flow import (
    STATE_TO_DB,
    TRANSITIONS,
    TaskFlowError,
    active_db_statuses,
    can_transition,
    current_state,
    initial_db_status,
    is_terminal,
    validate_transition,
)


def test_p1_state_machine():
    """Part 1：状态机纯函数"""
    # 映射
    assert STATE_TO_DB["created"] == "pending"
    assert STATE_TO_DB["in_progress"] == "processing"
    assert STATE_TO_DB["completed"] == "completed"
    assert STATE_TO_DB["cancelled"] == "cancelled"

    # 初始状态
    assert initial_db_status() == "pending"

    # 合法转移
    assert validate_transition("pending", "in_progress") == "processing"
    assert validate_transition("processing", "submitted") == "processing"
    assert validate_transition("processing", "completed") == "completed"
    assert validate_transition("pending", "cancelled") == "cancelled"

    # 非法转移（completed 是终态）
    try:
        validate_transition("completed", "in_progress")
        assert False, "completed 不应可转移"
    except TaskFlowError:
        pass

    # 非法状态
    try:
        validate_transition("pending", "unknown_state")
        assert False, "未知状态应抛错"
    except TaskFlowError:
        pass

    # 终态
    assert is_terminal("completed")
    assert is_terminal("cancelled")
    assert not is_terminal("pending")

    # active 状态
    assert "pending" in active_db_statuses()
    assert "processing" in active_db_statuses()

    # 映射
    assert current_state("pending") == "assigned"
    assert current_state("processing") == "in_progress"

    # TRANSITIONS 结构完整
    assert "cancelled" in TRANSITIONS["assigned"]
    assert "completed" in TRANSITIONS["in_progress"]

    print("✓ Part1 状态机纯函数")


def test_p2_transition_integration():
    """Part 2：task_service.transition 集成"""
    from work_agent.core.container import task_service
    from work_agent.db.session import SessionLocal
    from work_agent.repositories.user_repository import UserRepository

    db = SessionLocal()
    try:
        target = UserRepository().get_by_username(db, "A研发员工")
    finally:
        db.close()

    # 建任务
    task = task_service.create_task(
        creator_tenant_id="1",
        title="生命周期测试任务",
        creator_id=1,
        employee_id=target.id,
        department="研发部",
        deadline=datetime.now() + timedelta(days=5),
    )

    try:
        # pending → in_progress
        r = task_service.transition(
            tenant_id="1",
            task_id=task.id,
            to_state="in_progress",
        )
        assert r["status"] == "transitioned", r
        assert r["task"]["status"] == "processing", r

        # processing → completed
        r2 = task_service.transition(
            tenant_id="1",
            task_id=task.id,
            to_state="completed",
        )
        assert r2["status"] == "transitioned", r2
        assert r2["task"]["status"] == "completed", r2

        # completed → 非法转移
        r3 = task_service.transition(
            tenant_id="1",
            task_id=task.id,
            to_state="in_progress",
        )
        assert r3["status"] == "invalid_transition", r3

        # 跨租户 → TenantAccessDenied
        from work_agent.core.exceptions import TenantAccessDenied
        try:
            task_service.transition(
                tenant_id="2",
                task_id=task.id,
                to_state="cancelled",
            )
            assert False, "跨租户应拒绝"
        except TenantAccessDenied:
            pass

        print("✓ Part2 transition 集成")
    finally:
        # 清理
        db2 = SessionLocal()
        try:
            from work_agent.db.models.task import Task
            obj = db2.query(Task).filter(Task.id == task.id).first()
            if obj:
                db2.delete(obj)
                db2.commit()
        finally:
            db2.close()


def test_p3_policy_permission():
    """Part 3：Policy 权限（超管可取消/经理拒绝）"""
    from work_agent.agent.context import AgentContext
    from work_agent.agent.policy import policy_service
    from work_agent.agent.schemas import IntentType, PlanResult, PlanStep

    def _ctx(permissions, role_codes):
        return AgentContext(
            request_id="test-flow",
            tenant_id="1",
            user_id=1,
            username="tester",
            department="研发部",
            role="员工",
            permissions=set(permissions),
            role_codes=set(role_codes),
        )

    def _plan():
        return PlanResult(
            kind="task",
            intent=IntentType.SUBMIT_TASK,
            steps=[
                PlanStep(
                    step_id=1,
                    tool="task_tool",
                    action="transition",
                    args={"to_state": "cancelled"},
                ),
            ],
        )

    # 超管（有 task:manage）→ 通过
    admin = _ctx(
        ["task:manage", "task:view"],
        ["SUPER_ADMIN"],
    )
    decision = policy_service.evaluate(
        intent=IntentType.SUBMIT_TASK,
        plan=_plan(),
        context=admin,
    )
    assert decision.allowed, decision

    # 经理（DEPARTMENT_ADMIN，无 task:manage）→ 拒绝
    mgr = _ctx(
        ["task:view", "task:create"],
        ["DEPARTMENT_ADMIN"],
    )
    decision2 = policy_service.evaluate(
        intent=IntentType.SUBMIT_TASK,
        plan=_plan(),
        context=mgr,
    )
    assert not decision2.allowed, decision2
    assert "task:manage" in decision2.message, decision2.message

    print("✓ Part3 Policy 权限（超管可取消/经理拒绝）")


def test():
    print("== Task Lifecycle 状态机测试 ==")
    test_p1_state_machine()
    test_p2_transition_integration()
    test_p3_policy_permission()
    print("Task Lifecycle 测试全部通过")


if __name__ == "__main__":
    test()
