"""
任务督导模块测试套件

Part 0  迁移 + 权限（幂等）
Part 1  TaskService：创建/列表/提交/确认/取消（确定性）
Part 2  Intent + Planner：任务意图路由
Part 3  TaskAgent 端到端（list/submit/confirm/complete）
Part 4  越权隔离（跨租户待确认不可见）

用法：
    python -m work_agent.scripts.test_task_agent
"""

from work_agent.agent.agents.task_agent import TaskAgent
from work_agent.agent.context import AgentContext
from work_agent.agent.planner import agent_planner
from work_agent.agent.router.intent_router import IntentRouter
from work_agent.agent.schemas import IntentType
from work_agent.db.models.task import (
    Task,
    TaskPendingUpdate,
    TaskUpdate,
)
from work_agent.db.session import SessionLocal
from work_agent.repositories.task_repository import TaskRepository
from work_agent.repositories.user_repository import UserRepository
from work_agent.services.rbac_service import RBACService
from work_agent.services.task_service import task_service
from work_agent.scripts.migrate_tasks import migrate
from work_agent.scripts.seed_rbac import seed_rbac


def _setup():

    migrate()

    seed_rbac()

    _cleanup_test_tasks()


def _cleanup_test_tasks() -> None:

    """
    清理历史测试任务，保证测试幂等（可重复运行）
    """

    db = SessionLocal()

    try:

        employees = [
            UserRepository().get_by_username(db, name)
            for name in ("A财务员工", "B市场员工")
        ]

        ids = [
            u.id
            for u in employees
            if u
        ]

        if not ids:

            return

        db.query(TaskPendingUpdate).filter(
            TaskPendingUpdate.employee_id.in_(ids)
        ).delete(
            synchronize_session=False
        )

        db.query(TaskUpdate).filter(
            TaskUpdate.employee_id.in_(ids)
        ).delete(
            synchronize_session=False
        )

        db.query(Task).filter(
            Task.employee_id.in_(ids)
        ).delete(
            synchronize_session=False
        )

        db.commit()

    finally:

        db.close()


def _user(
        username: str
):

    db = SessionLocal()

    try:

        return UserRepository().get_by_username(
            db,
            username,
        )

    finally:

        db.close()


def _permissions(
        user
) -> set[str]:

    db = SessionLocal()

    try:

        return RBACService().get_permission_codes(
            db,
            user.id,
        )

    finally:

        db.close()


# ======================
# Part 1 服务层（确定性）
# ======================

def test_service():

    emp = _user("A财务员工")

    assert emp, "需要 A财务员工 测试用户"

    task = task_service.create_task(
        tenant_id=emp.tenant_id,
        title="财务模块开发",
        description="完成报销接口与审批流程",
        creator_id=emp.id,
        employee_id=emp.id,
        department="财务部",
        priority="high",
    )

    # 列表包含
    tasks = task_service.list_employee_tasks(
        tenant_id=emp.tenant_id,
        employee_id=emp.id,
    )

    assert any(
        t.id == task.id
        for t in tasks
    )

    # 提交 → 待确认
    result = task_service.submit_progress_feedback(
        tenant_id=emp.tenant_id,
        employee_id=emp.id,
        content=(
            f"提交{task.title} 完成50% "
            "数据库已完成"
        ),
    )

    assert result["status"] == "awaiting_confirmation", result

    # 确定性确认：直接写 pending 再确认（不依赖 LLM 解析精度）
    db = SessionLocal()

    try:

        TaskRepository().upsert_pending(
            db,
            task_id=task.id,
            employee_id=emp.id,
            content="接口完成",
            parsed={
                "progress": 80,
                "summary": "完成报销接口",
                "done": ["报销接口"],
                "remaining": ["审批流程"],
            },
        )

    finally:

        db.close()

    conf = task_service.confirm_pending(
        tenant_id=emp.tenant_id,
        employee_id=emp.id,
    )

    assert conf["status"] == "confirmed", conf

    updated = task_service.get_task(
        tenant_id=emp.tenant_id,
        task_id=task.id,
    )

    assert updated.progress == 80, updated.progress

    updates = task_service.list_task_updates(
        tenant_id=emp.tenant_id,
        task_id=task.id,
    )

    assert len(updates) == 1, updates

    assert updates[0].ai_summary == "完成报销接口"

    # 取消流程
    task_service.submit_progress_feedback(
        tenant_id=emp.tenant_id,
        employee_id=emp.id,
        content=(
            f"提交{task.title} 完成60%"
        ),
    )

    cancel = task_service.cancel_pending(
        tenant_id=emp.tenant_id,
        employee_id=emp.id,
    )

    assert cancel["status"] == "cancelled", cancel

    # 取消后无更新新增
    updates2 = task_service.list_task_updates(
        tenant_id=emp.tenant_id,
        task_id=task.id,
    )

    assert len(updates2) == 1, updates2

    print("Part 1 ✅ 服务层（创建/列表/提交/确认/取消）")

    return task


# ======================
# Part 2 意图 + 规划
# ======================

def test_intent_planner():

    emp = _user("A财务员工")

    context = AgentContext.build(
        user=emp,
        channel="wechat",
    )

    router = IntentRouter()

    intent1 = router.route(
        "我的任务",
        user_context=context.to_user_context(),
        tenant_context={"tenant_id": context.tenant_id},
    )

    assert intent1.intent == IntentType.TASK_MANAGEMENT, intent1

    plan1 = agent_planner.plan(
        message="我的任务",
        intent_result=intent1,
        context=context,
    )

    assert plan1.kind == "task", plan1.kind

    assert plan1.steps[0].tool == "task_tool", plan1.steps

    assert plan1.steps[0].action == "list", plan1.steps[0].action

    intent2 = router.route(
        "确认",
        user_context=context.to_user_context(),
        tenant_context={"tenant_id": context.tenant_id},
    )

    plan2 = agent_planner.plan(
        message="确认",
        intent_result=intent2,
        context=context,
    )

    assert plan2.kind == "task", plan2.kind

    assert plan2.steps[0].action == "confirm", plan2.steps[0].action

    print("Part 2 ✅ 意图路由 + 规划（我的任务/确认）")


# ======================
# Part 3 TaskAgent 端到端
# ======================

def test_agent(task) -> None:

    emp = _user("A财务员工")

    context = AgentContext.build(
        user=emp,
        channel="wechat",
        permissions=_permissions(emp),
    )

    agent = TaskAgent()

    # 查看任务
    intent = IntentRouter().route(
        "我的任务",
        user_context=context.to_user_context(),
        tenant_context={"tenant_id": context.tenant_id},
    )

    plan = agent_planner.plan(
        message="我的任务",
        intent_result=intent,
        context=context,
    )

    result = agent.run(
        context=context,
        plan=plan,
        message="我的任务",
    )

    assert "财务模块开发" in result.response, result.response

    # 提交进度 → 待确认
    intent = IntentRouter().route(
        "提交财务模块开发任务 完成70% 审批流程还没做",
        user_context=context.to_user_context(),
        tenant_context={"tenant_id": context.tenant_id},
    )

    plan = agent_planner.plan(
        message="提交财务模块开发任务 完成70% 审批流程还没做",
        intent_result=intent,
        context=context,
    )

    result = agent.run(
        context=context,
        plan=plan,
        message="提交财务模块开发任务 完成70% 审批流程还没做",
    )

    assert "确认提交吗" in result.response, result.response

    # 确认
    intent = IntentRouter().route(
        "确认",
        user_context=context.to_user_context(),
        tenant_context={"tenant_id": context.tenant_id},
    )

    plan = agent_planner.plan(
        message="确认",
        intent_result=intent,
        context=context,
    )

    result = agent.run(
        context=context,
        plan=plan,
        message="确认",
    )

    assert "已确认" in result.response, result.response

    # 完成任务 → 100%
    intent = IntentRouter().route(
        "任务完成",
        user_context=context.to_user_context(),
        tenant_context={"tenant_id": context.tenant_id},
    )

    plan = agent_planner.plan(
        message="任务完成",
        intent_result=intent,
        context=context,
    )

    result = agent.run(
        context=context,
        plan=plan,
        message="任务完成",
    )

    assert "确认提交吗" in result.response, result.response

    intent = IntentRouter().route(
        "确认",
        user_context=context.to_user_context(),
        tenant_context={"tenant_id": context.tenant_id},
    )

    plan = agent_planner.plan(
        message="确认",
        intent_result=intent,
        context=context,
    )

    result = agent.run(
        context=context,
        plan=plan,
        message="确认",
    )

    assert "已确认" in result.response, result.response

    final = task_service.get_task(
        tenant_id=emp.tenant_id,
        task_id=task.id,
    )

    assert final.progress == 100, final.progress

    assert final.status == "completed", final.status

    print("Part 3 ✅ TaskAgent 端到端（list/submit/confirm/complete）")


# ======================
# Part 4 越权隔离
# ======================

def test_isolation():

    emp_a = _user("A财务员工")

    emp_b = _user("B市场员工")

    assert emp_b, "需要 B市场员工 测试用户"

    # A 提交待确认
    task_service.submit_progress_feedback(
        tenant_id=emp_a.tenant_id,
        employee_id=emp_a.id,
        content=(
            "提交财务模块开发 完成90%"
        ),
    )

    # B（不同租户）确认 → 应为 no_pending
    conf = task_service.confirm_pending(
        tenant_id=emp_b.tenant_id,
        employee_id=emp_b.id,
    )

    assert conf["status"] == "no_pending", conf

    # 取消 A 的待确认，避免影响其他测试
    task_service.cancel_pending(
        tenant_id=emp_a.tenant_id,
        employee_id=emp_a.id,
    )

    print("Part 4 ✅ 越权隔离（跨租户待确认不可见）")


def test():

    _setup()

    task = test_service()

    test_intent_planner()

    test_agent(task)

    test_isolation()


if __name__ == "__main__":

    test()
