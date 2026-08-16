"""
Enterprise Agent 测试（Phase 1：Agent 基础能力）

Part A  BaseTool 权限钩子（REQUIRED_PERMISSION / PERMISSION_MAP / check_permission / denied）
Part A2 AgentContext.role_codes 注入
Part A3 ToolRegistry.list_tools 含权限信息
Part A4 TaskTool.input_schema action enum 完整（detail/submit_all）

用法：
    python -m work_agent.scripts.test_enterprise_agent
"""

from types import SimpleNamespace

# 副作用：触发 config.py 全局 stdout/stderr UTF-8 重配置（Windows GBK 兼容）
import work_agent.config  # noqa: F401

from work_agent.agent.context import AgentContext
from work_agent.agent.tools.base import BaseTool
from work_agent.agent.tools.registry import tool_registry
from work_agent.agent.tools.task_tool import TaskTool


def _ctx(
        permissions: set[str] | None = None,
        role_codes: set[str] | None = None,
        tenant_id: str = "1",
        department: str = "研发部",
):
    return AgentContext(
        request_id="test-1",
        tenant_id=tenant_id,
        user_id=1,
        username="tester",
        department=department,
        role="员工",
        permissions=set(permissions or []),
        role_codes=set(role_codes or []),
    )


def test_a_base_tool_permission_hook():
    """Part A1：BaseTool 权限钩子"""

    class FakeRequiredTool(BaseTool):
        REQUIRED_PERMISSION = "task:notify"

        def execute(self, **kwargs):
            return {}

    class FakeMappedTool(BaseTool):
        PERMISSION_MAP = {"delete": "document:delete", "view": "document:view"}

        def execute(self, **kwargs):
            return {}

    # REQUIRED_PERMISSION 缺失 → denied
    ctx_no_perm = _ctx(permissions={"task:view"})
    t = FakeRequiredTool()
    assert t.check_permission(ctx_no_perm) == "task:notify"
    denied = t.denied("task:notify")
    assert denied["error"] == "permission_denied"
    assert "task:notify" in denied["message"]

    # 有权限 → 通过
    ctx_ok = _ctx(permissions={"task:notify"})
    assert t.check_permission(ctx_ok) is None

    # PERMISSION_MAP action 维度
    m = FakeMappedTool()
    assert m.check_permission(_ctx({"document:view"}), "delete") == "document:delete"
    assert m.check_permission(_ctx({"document:view"}), "view") is None
    assert m.check_permission(_ctx({"document:view"}), "unknown") is None

    print("✓ PartA1 BaseTool 权限钩子")


def test_a2_context_role_codes():
    """Part A2：AgentContext.role_codes 注入与缺省"""
    ctx = _ctx(
        permissions={"task:view"},
        role_codes={"DEPARTMENT_ADMIN"},
    )
    assert ctx.role_codes == {"DEPARTMENT_ADMIN"}
    assert ctx.permissions == {"task:view"}

    # 缺省为空集（不传 role_codes 向后兼容）
    ctx_default = _ctx()
    assert ctx_default.role_codes == set()

    # build() 注入 role_codes
    user = SimpleNamespace(
        tenant_id="1", id=9, username="u", department="研发部", role="员工",
    )
    built = AgentContext.build(
        user=user,
        permissions={"task:view"},
        role_codes={"USER"},
    )
    assert built.role_codes == {"USER"}
    print("✓ PartA2 AgentContext.role_codes")


def test_a3_registry_permission_info():
    """Part A3：ToolRegistry.list_tools 含权限信息"""
    tools = {t["name"]: t for t in tool_registry.list_tools()}
    assert "task_tool" in tools

    task_info = tools["task_tool"]
    assert "required_permission" in task_info
    assert "permission_map" in task_info
    # task_tool 用 PERMISSION_MAP
    assert task_info["permission_map"].get("list") == "task:view"

    # 每个工具都有 name/description/input_schema（不破坏原有契约）
    for t in tool_registry.list_tools():
        assert t["name"]
        assert "description" in t
        assert "input_schema" in t
    print("✓ PartA3 ToolRegistry 权限信息")


def test_a4_task_tool_schema():
    """Part A4：TaskTool.input_schema action enum 完整"""
    schema = TaskTool().input_schema
    actions = schema["properties"]["action"]["enum"]
    for expected in ["list", "detail", "submit", "submit_all", "confirm", "cancel", "complete"]:
        assert expected in actions, f"input_schema 缺少 action: {expected}"
    # PERMISSION_MAP 与 schema 对齐
    assert set(TaskTool.PERMISSION_MAP.keys()) == set(actions)
    print("✓ PartA4 TaskTool input_schema")


# ======================
# Phase 2：任务查询能力
# ======================

from work_agent.agent.tools.user_tool import UserTool


def _db_user(username: str):
    from work_agent.db.session import SessionLocal
    from work_agent.repositories.user_repository import UserRepository
    db = SessionLocal()
    try:
        return UserRepository().get_by_username(db, username)
    finally:
        db.close()


def test_b_user_tool():
    """Part B：user_tool 解析员工 / 列部门成员"""
    tool = UserTool()

    # 有权限（task:view）的员工上下文（租户1）
    ctx_emp = _ctx(permissions={"task:view"}, role_codes={"USER"}, tenant_id="1")

    # resolve：按 real_name 精确（A研发员工 在租户1）
    r = tool.execute(context=ctx_emp, action="resolve", name="A研发员工")
    assert r["status"] == "found", r
    assert any(u["username"] == "A研发员工" for u in r["users"])

    # resolve：按 username
    r2 = tool.execute(context=ctx_emp, action="resolve", name="dept_admin_A")
    assert r2["status"] == "found", r2
    assert any(u["real_name"] == "dept_admin_A" for u in r2["users"])

    # resolve：不存在
    r3 = tool.execute(context=ctx_emp, action="resolve", name="不存在的员工XYZ")
    assert r3["status"] == "not_found", r3

    # list_department：租户1 研发部
    r4 = tool.execute(context=ctx_emp, action="list_department", department="研发部")
    assert r4["status"] == "found", r4
    assert len(r4["users"]) > 0
    assert all(u["department"] == "研发部" for u in r4["users"])

    # 无 task:view → denied
    ctx_no_perm = _ctx(permissions={"document:view"}, role_codes={"USER"}, tenant_id="1")
    r5 = tool.execute(context=ctx_no_perm, action="resolve", name="A研发员工")
    assert r5["error"] == "permission_denied", r5

    print("✓ PartB user_tool（解析/列部门/无权限拒绝）")


def test_b2_department_scope():
    """Part B2：check_department_scope（DEPARTMENT_ADMIN 仅本部门）"""
    from work_agent.agent.tools.permissions import check_department_scope

    # 部门管理员（研发部）→ 本部门通过
    ctx_dept = _ctx(
        permissions={"task:view"}, role_codes={"DEPARTMENT_ADMIN"},
        tenant_id="1", department="研发部",
    )
    assert check_department_scope(ctx_dept, "研发部") is True
    # 跨部门拒绝
    assert check_department_scope(ctx_dept, "财务部") is False

    # 超级管理员 → 放行任意部门
    ctx_admin = _ctx(
        permissions={"task:view"}, role_codes={"SUPER_ADMIN"},
        tenant_id="", department="管理层",
    )
    assert check_department_scope(ctx_admin, "财务部") is True

    print("✓ PartB2 check_department_scope")


def test_d_department_tasks():
    """Part D：department_tasks 部门任务清单 + 作用域"""
    from work_agent.agent.tools.task_tool import TaskTool
    from work_agent.core.container import task_service
    from work_agent.db.session import SessionLocal

    tool = TaskTool()

    # 准备：租户1 研发部一个任务（执行人 dept_admin_A 或某研发员工）
    dept_emp = _db_user("dept_admin_A")
    assert dept_emp, "缺少 dept_admin_A"

    # 新建任务（department=研发部，执行人=dept_admin_A）
    from datetime import datetime, timedelta
    task = task_service.create_task(
        creator_tenant_id="1",
        title="部门任务测试项",
        creator_id=dept_emp.id,
        employee_id=dept_emp.id,
        department="研发部",
        deadline=datetime.now() + timedelta(days=5),
    )

    try:
        # 部门管理员（研发部）查本部门 → 可见
        ctx_dept = _ctx(
            permissions={"task:view"}, role_codes={"DEPARTMENT_ADMIN"},
            tenant_id="1", department="研发部",
        )
        r = tool.execute(context=ctx_dept, action="department_tasks", department="研发部")
        assert "error" not in r, r
        assert r["department"] == "研发部"
        assert any(t["id"] == task.id for t in r["tasks"]), r

        # 部门管理员（财务部角色）查研发部 → 拒绝
        ctx_other = _ctx(
            permissions={"task:view"}, role_codes={"DEPARTMENT_ADMIN"},
            tenant_id="1", department="财务部",
        )
        r2 = tool.execute(context=ctx_other, action="department_tasks", department="研发部")
        assert r2["error"] == "permission_denied", r2

        # 超级管理员（空租户）查研发部 → 全量可见
        ctx_admin = _ctx(
            permissions={"task:view"}, role_codes={"SUPER_ADMIN"},
            tenant_id="", department="管理层",
        )
        r3 = tool.execute(context=ctx_admin, action="department_tasks", department="研发部")
        assert "error" not in r3, r3
        assert any(t["id"] == task.id for t in r3["tasks"])

        # 普通员工（USER）查部门任务 → 无部门维度，按权限码放行？USER 有 task:view，
        # 但业务上员工不应查部门。这里按设计：USER 无 DEPARTMENT_ADMIN role → check_department_scope 放行，
        # 但权限码仍 task:view。实际部门维度限制靠 role。测试记录行为即可。
        ctx_user = _ctx(
            permissions={"task:view"}, role_codes={"USER"},
            tenant_id="1", department="研发部",
        )
        r4 = tool.execute(context=ctx_user, action="department_tasks", department="研发部")
        assert "error" not in r4, r4  # USER 不限制部门（由前端/权限码约束）

        print("✓ PartD department_tasks（本部门可见/跨部门拒绝/管理员全量）")
    finally:
        # 清理测试任务
        from work_agent.core.container import task_service as ts
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
    print("== Enterprise Agent 测试（Phase 1 + Phase 2）==")
    test_a_base_tool_permission_hook()
    test_a2_context_role_codes()
    test_a3_registry_permission_info()
    test_a4_task_tool_schema()
    test_b_user_tool()
    test_b2_department_scope()
    test_d_department_tasks()
    print("Enterprise Agent 测试全部通过")


if __name__ == "__main__":
    test()
