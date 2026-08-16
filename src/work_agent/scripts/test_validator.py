"""
Task Command Validator 测试（Phase 8）

Part 1  Schema Validator（结构校验，纯函数）
Part 2  Business Rule Validator（执行人存在/同部门/查重，DB 集成）

用法：
    python -m work_agent.scripts.test_validator
"""

# 副作用：触发 config.py stdout UTF-8 重配置（Windows GBK）
import work_agent.config  # noqa: F401

from work_agent.agent.context import AgentContext
from work_agent.agent.tools.validator import task_command_validator


def _ctx(
        permissions: set[str] | None = None,
        role_codes: set[str] | None = None,
        department: str = "研发部",
):
    return AgentContext(
        request_id="test-validator",
        tenant_id="1",
        user_id=1,
        username="tester",
        department=department,
        role="员工",
        permissions=set(permissions or []),
        role_codes=set(role_codes or []),
    )


def test_schema_valid():
    """合法结构化命令 → 通过"""
    command = {
        "intent": "create_task",
        "command": {
            "type": "task.create",
            "assignee_name": "张三",
            "title": "客户合同审核",
            "deadline": "2026-08-20",
        },
    }
    r = task_command_validator.validate_command(command)
    assert r.valid, r.errors
    assert r.command["action"] == "create_task"
    assert r.command["title"] == "客户合同审核"
    print("✓ Schema 合法命令")


def test_schema_reject_free_text():
    """自由文本命令 → 拒绝"""
    command = {"text": "安排张三审核合同"}
    r = task_command_validator.validate_command(command)
    assert not r.valid, r
    assert any("结构化" in e for e in r.errors), r.errors
    print("✓ Schema 拒绝自由文本")


def test_schema_missing_fields():
    """缺 title/assignee → 拒绝"""
    command = {
        "command": {
            "type": "task.create",
            "title": "",
        },
    }
    r = task_command_validator.validate_command(command)
    assert not r.valid, r
    assert any("title" in e for e in r.errors), r.errors
    assert any("assignee" in e for e in r.errors), r.errors
    print("✓ Schema 缺字段")


def test_schema_bad_deadline():
    """非法 deadline → 拒绝"""
    command = {
        "command": {
            "type": "task.create",
            "assignee_name": "张三",
            "title": "客户合同审核",
            "deadline": "随便写的日期",
        },
    }
    r = task_command_validator.validate_command(command)
    assert not r.valid, r
    assert any("deadline" in e for e in r.errors), r.errors
    print("✓ Schema 非法 deadline")


def test_business_valid():
    """业务规则：执行人存在 + 同部门 → 通过"""
    ctx = _ctx(
        permissions={"task:create"},
        role_codes={"DEPARTMENT_ADMIN"},
    )
    # 员工A（租户1 财务部？需确认部门）—— 用 A研发员工（研发部）
    from work_agent.db.session import SessionLocal
    from work_agent.repositories.user_repository import UserRepository

    db = SessionLocal()
    try:
        target = UserRepository().get_by_username(db, "A研发员工")
    finally:
        db.close()

    assert target, "缺少 A研发员工"

    # 部门管理员研发部 安排 A研发员工（研发部）→ 通过
    r = task_command_validator.validate_business(
        context=ctx,
        assignee_id=target.id,
        assignee_name=target.real_name,
        title="客户合同审核",
        tenant_id="1",
    )
    assert r.valid, r.errors
    print("✓ 业务规则 同部门执行人通过")


def test_business_cross_department():
    """业务规则：跨部门执行人 → 拒绝"""
    ctx = _ctx(
        permissions={"task:create"},
        role_codes={"DEPARTMENT_ADMIN"},
    )
    from work_agent.db.session import SessionLocal
    from work_agent.repositories.user_repository import UserRepository

    db = SessionLocal()
    try:
        # A财务员工（财务部），部门管理员是研发部
        target = UserRepository().get_by_username(db, "A财务员工")
    finally:
        db.close()

    assert target, "缺少 A财务员工"

    r = task_command_validator.validate_business(
        context=ctx,
        assignee_id=target.id,
        assignee_name=target.real_name,
        title="客户合同审核",
        tenant_id="1",
    )
    assert not r.valid, r
    assert any("部门" in e for e in r.errors), r.errors
    print("✓ 业务规则 跨部门执行人拒绝")


def test_business_duplicate():
    """业务规则：重复任务 → 拒绝"""
    from datetime import datetime, timedelta

    from work_agent.core.container import task_service
    from work_agent.db.session import SessionLocal
    from work_agent.repositories.user_repository import UserRepository

    db = SessionLocal()
    try:
        target = UserRepository().get_by_username(db, "A研发员工")
    finally:
        db.close()

    ctx = _ctx(
        permissions={"task:create"},
        role_codes={"DEPARTMENT_ADMIN"},
    )

    # 先建一个任务（title=重复测试任务）
    task = task_service.create_task(
        creator_tenant_id="1",
        title="重复测试任务",
        creator_id=1,
        employee_id=target.id,
        department="研发部",
        deadline=datetime.now() + timedelta(days=5),
    )

    try:
        # 同执行人同 title → 查重拒绝
        r = task_command_validator.validate_business(
            context=ctx,
            assignee_id=target.id,
            assignee_name=target.real_name,
            title="重复测试任务",
            tenant_id="1",
        )
        assert not r.valid, r
        assert any("已存在" in e for e in r.errors), r.errors
        print("✓ 业务规则 重复任务拒绝")
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


def test():
    print("== Task Command Validator 测试 ==")
    test_schema_valid()
    test_schema_reject_free_text()
    test_schema_missing_fields()
    test_schema_bad_deadline()
    test_business_valid()
    test_business_cross_department()
    test_business_duplicate()
    print("Validator 测试全部通过")


if __name__ == "__main__":
    test()
