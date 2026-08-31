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

    # list_department：普通员工（USER）拒绝（仅部门经理可看本部门员工）
    r4 = tool.execute(context=ctx_emp, action="list_department", department="研发部")
    assert r4["error"] == "permission_denied", r4

    # list_department：部门经理（DEPARTMENT_ADMIN）本部门 → 名单
    ctx_dept = _ctx(
        permissions={"task:view"},
        role_codes={"DEPARTMENT_ADMIN"},
        tenant_id="1", department="研发部",
    )
    r4b = tool.execute(context=ctx_dept, action="list_department", department="研发部")
    assert r4b["status"] == "found", r4b
    assert len(r4b["users"]) > 0
    assert all(u["department"] == "研发部" for u in r4b["users"])
    # 返回姓名（real_name）+ 用户名（非 user_id 展示）
    first = r4b["users"][0]
    assert first["real_name"], "应返回姓名"

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

        # 普通员工（USER）查部门任务 → 拒绝（权限不足）
        ctx_user = _ctx(
            permissions={"task:view"}, role_codes={"USER"},
            tenant_id="1", department="研发部",
        )
        r4 = tool.execute(context=ctx_user, action="department_tasks", department="研发部")
        assert r4["error"] == "permission_denied", r4

        print("✓ PartD department_tasks（本部门可见/跨部门拒绝/管理员全量/员工拒绝）")

        # employee_tasks：部门经理查指定员工任务（按姓名）
        r_emp = tool.execute(
            context=ctx_dept,
            action="employee_tasks",
            query=f"查看{dept_emp.real_name}的任务",
        )
        assert "error" not in r_emp, r_emp
        assert r_emp["employee"] == dept_emp.real_name, r_emp
        assert any(t["id"] == task.id for t in r_emp["tasks"]), r_emp

        # employee_tasks：跨部门员工 → 拒绝
        ctx_dept_rd = _ctx(
            permissions={"task:view"}, role_codes={"DEPARTMENT_ADMIN"},
            tenant_id="1", department="研发部",
        )
        finance = _db_user("A财务员工")
        r_emp2 = tool.execute(
            context=ctx_dept_rd,
            action="employee_tasks",
            query=f"查看{finance.real_name}的任务",
        )
        assert r_emp2["error"] == "permission_denied", r_emp2

        # employee_tasks：普通员工 → 拒绝
        ctx_user2 = _ctx(
            permissions={"task:view"}, role_codes={"USER"},
            tenant_id="1", department="研发部",
        )
        r_emp3 = tool.execute(
            context=ctx_user2,
            action="employee_tasks",
            query=f"查看{dept_emp.real_name}的任务",
        )
        assert r_emp3["error"] == "permission_denied", r_emp3

        print("✓ PartD2 employee_tasks（按姓名查/跨部门拒绝/员工拒绝）")
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


# ======================
# Phase 3：任务创建 Agent（带确认）
# ======================


def _purge_test_tasks(employee_id: int):
    """删除测试标题残留任务（防止失败级联）"""
    from work_agent.db.models.task import Task
    from work_agent.db.session import SessionLocal
    db = SessionLocal()
    try:
        rows = db.query(Task).filter(
            Task.employee_id == employee_id,
            Task.title.in_(["客户系统测试", "接口开发", "接口联调测试", "财务审核"]),
        ).all()
        for t in rows:
            db.delete(t)
        db.commit()
    finally:
        db.close()


def _cleanup_pending_creates():
    from work_agent.db.models.task import TaskPendingCreate
    from work_agent.db.session import SessionLocal
    db = SessionLocal()
    try:
        db.query(TaskPendingCreate).delete()
        db.commit()
    finally:
        db.close()


def test_c_notification_tool():
    """Part C：notification_tool 企微/邮件提醒 + 部门作用域 + 权限"""
    from work_agent.agent.tools.notification_tool import NotificationTool
    from work_agent.config import settings

    tool = NotificationTool()

    # 目标员工：A研发员工（租户1 研发部，有 wechat）
    target = _db_user("A研发员工")
    assert target, "缺少 A研发员工"

    # mock 企微发送
    import work_agent.wechat.client as wc

    class FakeClient:
        def send_text_message(self, user_id, content):
            return {"errcode": 0, "errmsg": "ok"}

    old_client = wc.wecom_client
    wc.wecom_client = FakeClient()

    try:
        # 部门管理员（研发部）有 task:notify → send_wechat 成功
        ctx_dept = _ctx(
            permissions={"task:view", "task:notify"},
            role_codes={"DEPARTMENT_ADMIN"},
            tenant_id="1", department="研发部",
        )
        r = tool.execute(
            context=ctx_dept,
            action="send_wechat",
            employee_id=target.id,
            content="请尽快完成测试任务",
        )
        assert r.get("ok") is True, r
        assert r["status"] == "sent", r

        # 跨部门提醒被拒（研发部 admin 提醒 财务部 员工）
        ctx_dept_rd = _ctx(
            permissions={"task:view", "task:notify"},
            role_codes={"DEPARTMENT_ADMIN"},
            tenant_id="1", department="研发部",
        )
        finance = _db_user("A财务员工")
        r2 = tool.execute(
            context=ctx_dept_rd,
            action="send_wechat",
            employee_id=finance.id,
            content="提醒",
        )
        assert r2["error"] == "permission_denied", r2

        # USER 无 task:notify → denied
        ctx_user = _ctx(
            permissions={"task:view"},
            role_codes={"USER"},
            tenant_id="1",
        )
        r3 = tool.execute(
            context=ctx_user,
            action="send_wechat",
            employee_id=target.id,
            content="提醒",
        )
        assert r3["error"] == "permission_denied", r3

        # send_email：SMTP 未启用 → email_disabled（明确提示，不走失败流程）
        # 用有 email 的用户（统计创建者）+ SUPER_ADMIN（无部门限制）
        # 统计创建者 由 test_task_stats 创建；本测试字母序在其前，find-or-create 保证自足
        email_user = _db_user("统计创建者")
        if email_user is None:
            from work_agent.db.session import SessionLocal
            from work_agent.repositories.user_repository import UserRepository
            from work_agent.services.auth_service import AuthService
            _db = SessionLocal()
            try:
                email_user = UserRepository().create(
                    _db,
                    username="统计创建者",
                    password_hash=AuthService.hash_password("test123"),
                    department="研发部",
                    role="管理员",
                    email="creator@test.com",
                    tenant_id="1",
                )
            finally:
                _db.close()
        ctx_admin = _ctx(
            permissions={"task:view", "task:notify"},
            role_codes={"SUPER_ADMIN"},
            tenant_id="1",
        )
        old_email = settings.email_enabled
        settings.email_enabled = False
        try:
            assert email_user, "缺少有 email 的用户（统计创建者）"
            r4 = tool.execute(
                context=ctx_admin,
                action="send_email",
                employee_id=email_user.id,
                subject="测试",
                content="测试邮件",
            )
            assert r4["status"] == "email_disabled", r4
            assert "未启用" in r4["detail"], r4
        finally:
            settings.email_enabled = old_email

        # 未绑定企微员工 → send_wechat 明确提示
        unbound = _db_user("督办测试未绑定")
        if unbound:
            r5 = tool.execute(
                context=ctx_dept,
                action="send_wechat",
                employee_id=unbound.id,
                content="提醒",
            )
            assert r5["error"] == "no_wechat_binding", r5

        print("✓ PartC notification_tool（企微发送/跨部门拒/无权限拒/SMTP未启用提示/未绑定提示）")
    finally:
        wc.wecom_client = old_client


def test_e_task_create_flow():
    """Part E：任务创建确认流（preview → confirm → created / cancel）"""
    from work_agent.core.container import task_service
    from work_agent.agent.tools.task_tool import TaskTool
    from work_agent.db.session import SessionLocal

    tool = TaskTool()

    # 用 dept_admin_A 作为创建者（DEPARTMENT_ADMIN，租户1，有 task:create）
    creator = _db_user("dept_admin_A")
    assert creator, "缺少 dept_admin_A"

    # 执行人：A研发员工（租户1 研发部）
    target = _db_user("A研发员工")
    assert target, "缺少 A研发员工"
    _purge_test_tasks(target.id)

    ctx_admin = _ctx(
        permissions={"task:view", "task:create"},
        role_codes={"DEPARTMENT_ADMIN"},
        tenant_id="1", department="研发部",
    )
    # 绑定创建者真实 id（AgentContext 里 user_id）
    ctx_admin.user_id = creator.id

    try:
        # 1. 发起创建 → awaiting_confirmation
        r = tool.execute(
            context=ctx_admin,
            action="create",
            content=f"给{target.real_name}安排客户系统测试任务，下周五完成",
        )
        assert r["status"] == "awaiting_confirmation", r
        draft = r["draft"]
        assert draft["title"], "应解析出任务名"
        assert draft["employee_id"] == target.id, "执行人应为 A研发员工"
        assert draft["deadline"] is not None, "下周五应解析出截止时间"
        print(f"  create preview: title={draft['title']} emp={draft['employee_name']} dl={draft['deadline']}")

        # 2. 缺字段 → need_info（无执行人）
        r2 = tool.execute(
            context=ctx_admin,
            action="create",
            content="我想发布一个新任务",
        )
        assert r2["status"] == "need_info", r2
        assert "employee_name" in r2["missing"], r2

        # 3. 再次发起创建，覆盖在途草稿（upsert）
        r3 = tool.execute(
            context=ctx_admin,
            action="create",
            content=f"给{target.real_name}安排接口开发任务，3天后完成",
        )
        assert r3["status"] == "awaiting_confirmation", r3
        assert "接口开发" in r3["draft"]["title"], r3

        # 4. 确认 → task_created（内部 create_task 落库）
        r4 = tool.execute(context=ctx_admin, action="confirm", content="确认")
        assert r4["status"] == "task_created", r4
        created_task_id = r4["task"]["id"]

        # 验证落库：执行人租户
        db = SessionLocal()
        try:
            from work_agent.db.models.task import Task
            task = db.query(Task).filter(Task.id == created_task_id).first()
            assert task is not None
            assert task.employee_id == target.id
            assert task.tenant_id == "1"  # 执行人租户
        finally:
            db.close()

        # 5. 无在途草稿时 confirm → 回退进度确认（no_pending）
        r5 = tool.execute(context=ctx_admin, action="confirm", content="确认")
        assert r5["status"] in ("no_pending", "no_tasks"), r5

        # 6. 取消流程
        tool.execute(
            context=ctx_admin,
            action="create",
            content=f"给{target.real_name}安排临时任务",
        )
        r6 = tool.execute(context=ctx_admin, action="cancel", content="取消")
        assert r6["status"] == "cancelled_create", r6

        # 7. 无 task:create 权限 → denied
        ctx_user_no_create = _ctx(
            permissions={"task:view"},
            role_codes={"USER"},
            tenant_id="1",
        )
        ctx_user_no_create.user_id = target.id
        r7 = tool.execute(
            context=ctx_user_no_create,
            action="create",
            content="给员工A安排任务",
        )
        assert r7["error"] == "permission_denied", r7

        print("✓ PartE 任务创建确认流（preview/need_info/confirm created/cancel/权限拒绝）")

        # 清理已创建任务
        db = SessionLocal()
        try:
            from work_agent.db.models.task import Task
            obj = db.query(Task).filter(Task.id == created_task_id).first()
            if obj:
                db.delete(obj)
                db.commit()
        finally:
            db.close()

    finally:
        _cleanup_pending_creates()


def test_e3_multi_turn_create():
    """Part E3：多轮补充执行人（need_info → 回姓名 → 合并草稿 → 确认创建）"""
    from work_agent.agent.tools.task_tool import TaskTool
    from work_agent.core.container import task_service
    from work_agent.db.session import SessionLocal

    tool = TaskTool()

    creator = _db_user("dept_admin_A")
    assert creator, "缺少 dept_admin_A"
    target = _db_user("A研发员工")
    assert target, "缺少 A研发员工"
    _purge_test_tasks(target.id)

    ctx_admin = _ctx(
        permissions={"task:view", "task:create"},
        role_codes={"DEPARTMENT_ADMIN"},
        tenant_id="1", department="研发部",
    )
    ctx_admin.user_id = creator.id

    try:
        # 1. 首次发起（缺执行人）→ need_info，部分草稿落库
        r1 = tool.execute(
            context=ctx_admin,
            action="create",
            content="发布一个客户系统测试任务，下周五完成",
        )
        assert r1["status"] == "need_info", r1
        assert "employee_name" in r1["missing"], r1

        # 2. 回单独姓名（短消息）→ 合并在途草稿 → awaiting_confirmation
        r2 = tool.execute(
            context=ctx_admin,
            action="create",
            content=target.real_name,
        )
        assert r2["status"] == "awaiting_confirmation", r2
        draft = r2["draft"]
        assert draft["employee_id"] == target.id, draft
        assert draft["title"], "标题应从部分草稿继承"
        assert "客户系统测试" in draft["title"], draft["title"]

        # 3. 确认 → 落库
        r3 = tool.execute(context=ctx_admin, action="confirm", content="确认")
        assert r3["status"] == "task_created", r3
        created_task_id = r3["task"]["id"]
        db = SessionLocal()
        try:
            from work_agent.db.models.task import Task
            task = db.query(Task).filter(Task.id == created_task_id).first()
            assert task is not None and task.employee_id == target.id
        finally:
            db.close()

        # 4. 缺执行人 → 回不存在的姓名 → employee_not_found（提示查看名单）
        tool.execute(
            context=ctx_admin,
            action="create",
            content="发布一个财务审核任务",
        )
        r4 = tool.execute(
            context=ctx_admin,
            action="create",
            content="不存在的员工XYZ",
        )
        assert r4["status"] == "employee_not_found", r4
        assert "查看本部门员工" in r4["message"], r4

        # 5. 新句式「发布任务给X做…」→ 直接抽出执行人
        #   （注意：标题避开第3步已创建的同名任务，防查重拦截）
        r5 = tool.execute(
            context=ctx_admin,
            action="create",
            content=f"发布任务给{target.real_name}做接口联调测试",
        )
        assert r5["status"] == "awaiting_confirmation", r5
        assert r5["draft"]["employee_id"] == target.id, r5

        print("✓ PartE3 多轮补充执行人（need_info → 回姓名 → 合并 → 创建）")

        # 清理已创建任务
        db = SessionLocal()
        try:
            from work_agent.db.models.task import Task
            obj = db.query(Task).filter(Task.id == created_task_id).first()
            if obj:
                db.delete(obj)
                db.commit()
        finally:
            db.close()

    finally:
        _cleanup_pending_creates()


def test_e4_supplement_routing():
    """Part E4：补充回复意图路由（在途草稿未完成 → 短消息强制 create）"""
    from work_agent.agent.router.intent_router import IntentRouter
    from work_agent.agent.tools.task_tool import TaskTool

    creator = _db_user("dept_admin_A")
    assert creator, "缺少 dept_admin_A"

    ctx_admin = _ctx(
        permissions={"task:view", "task:create"},
        role_codes={"DEPARTMENT_ADMIN"},
        tenant_id="1", department="研发部",
    )
    ctx_admin.user_id = creator.id

    try:
        # 无草稿：短消息不劫持（不强制 create）
        assert IntentRouter._create_supplement_override(
            "张三", {"user_id": creator.id},
        ) is None

        # 建一个未完成草稿（缺执行人）
        tool = TaskTool()
        r1 = tool.execute(
            context=ctx_admin,
            action="create",
            content="发布一个客户系统测试任务",
        )
        assert r1["status"] == "need_info", r1

        # 有未完成草稿：短姓名 → 强制 create（补充回复）
        o = IntentRouter._create_supplement_override(
            "张三", {"user_id": creator.id},
        )
        assert o is not None and o.intent == "create_task", o
        assert o.tool == "task_tool", o

        # 确认/取消 仍归确认/取消流程（不被劫持为 create）
        assert IntentRouter._create_supplement_override(
            "确认", {"user_id": creator.id},
        ) is None

        print("✓ PartE4 补充回复意图路由（在途草稿 → 短消息强制 create）")
    finally:
        _cleanup_pending_creates()


def test_h_department_members():
    """Part H：查看本部门员工（意图路由 → plan → Policy → 姓名格式化）"""
    from work_agent.agent.agents.task_agent import TaskAgent
    from work_agent.agent.planner import agent_planner
    from work_agent.agent.policy import policy_service
    from work_agent.agent.router.intent_router import IntentRouter

    router = IntentRouter()

    # 1. 规则回退 → query_department_members（user_tool）
    intent = router._fallback("查看本部门员工")
    assert intent.intent == "query_department_members", intent.intent
    assert intent.tool == "user_tool", intent.tool

    intent2 = router._fallback("部门有哪些员工")
    assert intent2.intent == "query_department_members", intent2.intent

    # 任务语境不误判（查看指定员工任务仍归 query_employee_task）
    intent3 = router._fallback("查看张三的任务")
    assert intent3.intent == "query_employee_task", intent3.intent

    # 2. planner → user_tool / list_department
    ctx_mgr = _ctx(
        permissions={"task:view"},
        role_codes={"DEPARTMENT_ADMIN"},
        tenant_id="1", department="研发部",
    )
    plan = agent_planner.plan(
        message="查看本部门员工",
        intent_result=intent,
        context=ctx_mgr,
    )
    assert plan.steps[0].tool == "user_tool", plan.steps
    assert plan.steps[0].action == "list_department", plan.steps

    # 3. Policy：经理放行，普通员工拒绝
    assert policy_service.evaluate(
        intent=intent.intent, plan=plan, context=ctx_mgr,
    ).allowed is True

    ctx_user = _ctx(
        permissions={"task:view"},
        role_codes={"USER"},
        tenant_id="1", department="研发部",
    )
    denied = policy_service.evaluate(
        intent=intent.intent, plan=plan, context=ctx_user,
    )
    assert denied.allowed is False, denied

    # 4. TaskAgent 格式化：姓名（用户名），不含 user_id
    agent = TaskAgent()
    result = agent.run(context=ctx_mgr, plan=plan, message="查看本部门员工")
    assert "员工名单" in result.response, result.response
    assert "研发部" in result.response, result.response
    assert "A研发员工" in result.response, result.response
    assert "user_id" not in result.response, result.response

    print("✓ PartH 查看本部门员工（路由 → plan → Policy → 姓名格式化）")


def test_h2_command_not_hijacked():
    """Part H2：命令词不被当作员工姓名/任务标题（生产回归）"""
    from work_agent.agent.router.intent_router import IntentRouter
    from work_agent.agent.tools.task_tool import TaskTool

    router = IntentRouter()

    # 1. 内置命令 → query_department_members（确定性，不依赖 LLM/草稿）
    for cmd in ("查看本部门员工", "查看名单", "查看员工", "员工名单", "看名单", "部门成员"):
        r = router.route(cmd, user_context={"user_id": 1, "tenant_id": "1"})
        assert r.intent == "query_department_members", (cmd, r.intent)
        assert r.tool == "user_tool", (cmd, r.tool)

    # 任务语境不误判（"查看张三的任务" → 员工任务）
    r_task = router.route("查看张三的任务", user_context={"user_id": 1, "tenant_id": "1"})
    assert r_task.intent == "query_employee_task", r_task.intent

    # 2. 有在途未完成草稿时，命令仍不被劫持为 create/姓名
    creator = _db_user("dept_admin_A")
    assert creator, "缺少 dept_admin_A"

    ctx = _ctx(
        permissions={"task:view", "task:create"},
        role_codes={"DEPARTMENT_ADMIN"},
        tenant_id="1", department="研发部",
    )
    ctx.user_id = creator.id

    tool = TaskTool()

    try:
        # 造一个缺执行人的在途草稿
        r1 = tool.execute(
            context=ctx,
            action="create",
            content="发布一个客户系统测试任务",
        )
        assert r1["status"] == "need_info", r1

        # 命令 → 仍路由到部门员工（不被 supplement override 当姓名劫持）
        r2 = router.route(
            "查看本部门员工",
            user_context={"user_id": creator.id, "tenant_id": "1"},
        )
        assert r2.intent == "query_department_members", r2.intent

        # 纯姓名 → 仍作补充回复（create 合并续补）
        r3 = router.route(
            "张三",
            user_context={"user_id": creator.id, "tenant_id": "1"},
        )
        assert r3.intent == "create_task", r3.intent
    finally:
        _cleanup_pending_creates()

    print("✓ PartH2 命令词路由（查看名单/员工/本部门员工 不当作姓名/标题）")


def test_f_intent_planning():
    """Part F：task_create 意图路由 + plan"""
    from work_agent.agent.router.intent_router import IntentRouter
    from work_agent.agent.planner import agent_planner

    ctx = _ctx(
        permissions={"task:view", "task:create"},
        role_codes={"DEPARTMENT_ADMIN"},
        tenant_id="1", department="研发部",
    )

    router = IntentRouter()

    # 规则回退路径（不依赖 LLM，确定性）：安排 + 任务 → create_task
    intent = router._fallback("给张三安排客户系统测试任务")
    assert intent.intent == "create_task", intent.intent

    plan = agent_planner.plan(
        message="给张三安排客户系统测试任务，下周五完成",
        intent_result=intent,
        context=ctx,
    )
    assert plan.kind == "task", plan.kind
    assert plan.steps[0].tool == "task_tool", plan.steps
    assert plan.steps[0].action == "create", plan.steps
    print("✓ PartF task_create 意图路由 + plan")

    # employee_tasks：查看指定员工任务
    intent_emp = router._fallback("查看张三的任务")
    assert intent_emp.intent == "query_employee_task", intent_emp.intent
    assert intent_emp.entities.get("action") == "employee_tasks", intent_emp.entities

    plan_emp = agent_planner.plan(
        message="查看张三的任务",
        intent_result=intent_emp,
        context=ctx,
    )
    assert plan_emp.kind == "task", plan_emp.kind
    assert plan_emp.steps[0].tool == "task_tool", plan_emp.steps
    assert plan_emp.steps[0].action == "employee_tasks", plan_emp.steps
    print("✓ PartF2 employee_tasks 意图路由 + plan")


def test_e2_deadline_parse():
    """Part E2：_parse_deadline_text 确定性解析"""
    from work_agent.core.container import task_service
    from datetime import datetime, timedelta

    now = datetime.now()

    assert task_service._parse_deadline_text("明天") is not None
    assert task_service._parse_deadline_text("3天后") is not None
    assert task_service._parse_deadline_text("下周五") is not None
    assert task_service._parse_deadline_text("尽快") is not None
    assert task_service._parse_deadline_text("2026-12-31") is not None
    assert task_service._parse_deadline_text("") is None
    assert task_service._parse_deadline_text("随便写") is None
    print("✓ PartE2 _parse_deadline_text")


def test():
    print("== Enterprise Agent 测试（Phase 1-4）==")
    test_a_base_tool_permission_hook()
    test_a2_context_role_codes()
    test_a3_registry_permission_info()
    test_a4_task_tool_schema()
    test_b_user_tool()
    test_b2_department_scope()
    test_c_notification_tool()
    test_d_department_tasks()
    test_e_task_create_flow()
    test_e2_deadline_parse()
    test_e3_multi_turn_create()
    test_e4_supplement_routing()
    test_f_intent_planning()
    test_h_department_members()
    test_h2_command_not_hijacked()
    print("Enterprise Agent 测试全部通过")


if __name__ == "__main__":
    test()
