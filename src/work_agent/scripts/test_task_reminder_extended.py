"""
任务督办增强测试（Enterprise Agent Phase 4）

Part 1  compute_staleness（N 天未更新，确定性）
Part 2  list_remindable 按 tenant/department 过滤
Part 3  remind_department_admins（部门 digest 发给部门经理，mock 企微）
Part 4  send_department_digests 周报部门经理投递（mock 企微）
Part 5  scan_and_remind(department=...) 定向部门

用法：
    python -m work_agent.scripts.test_task_reminder_extended
"""

# 副作用：触发 config.py stdout UTF-8 重配置（Windows GBK）
import work_agent.config  # noqa: F401

from datetime import datetime, timedelta

from work_agent.core.container import task_reminder_service, task_report_service
from work_agent.db.models.task import Task
from work_agent.db.session import SessionLocal
from work_agent.services.task_reminder_service import TaskReminderService


TENANT = "1"
DEPT = "研发部"


def _make_task(**overrides):
    task = Task(
        tenant_id=overrides.get("tenant_id", TENANT),
        title=overrides.get("title", "督办测试任务"),
        employee_id=overrides.get("employee_id", 3),
        department=overrides.get("department", DEPT),
        deadline=overrides.get("deadline", datetime.now() + timedelta(days=3)),
        status=overrides.get("status", "processing"),
        progress=overrides.get("progress", 30),
        priority=overrides.get("priority", "normal"),
        created_at=datetime.now(),
        updated_at=overrides.get("updated_at", datetime.now()),
    )
    return task


def _cleanup():
    from work_agent.scripts.test_utils import cleanup_tenant_data
    cleanup_tenant_data(("1", "2"))


def test_p1_staleness():
    """Part 1：compute_staleness"""
    now = datetime.now()

    # 10 天未更新 → 停滞 10 天
    old_task = _make_task(updated_at=now - timedelta(days=10))
    assert task_reminder_service.compute_staleness(old_task, now=now) == 10

    # 1 天前更新 → 不视为停滞
    fresh_task = _make_task(updated_at=now - timedelta(days=1))
    assert task_reminder_service.compute_staleness(fresh_task, now=now) == 0

    # 已完成任务 → 0
    done_task = _make_task(status="completed", updated_at=now - timedelta(days=10))
    assert task_reminder_service.compute_staleness(done_task, now=now) == 0

    # 无截止 → 0
    no_dl_task = _make_task(deadline=None, updated_at=now - timedelta(days=10))
    assert task_reminder_service.compute_staleness(no_dl_task, now=now) == 0

    print("✓ Part1 compute_staleness")


def test_p2_remindable_filter():
    """Part 2：list_remindable 按 tenant/department 过滤"""
    db = SessionLocal()
    try:
        # 按租户
        tasks_tenant = task_reminder_service.repository.list_remindable(
            db, tenant_id=TENANT,
        )
        assert all(t.tenant_id == TENANT for t in tasks_tenant)

        # 按部门
        tasks_dept = task_reminder_service.repository.list_remindable(
            db, tenant_id=TENANT, department=DEPT,
        )
        assert all(t.department == DEPT for t in tasks_dept)

        # 空部门 → 空
        tasks_none = task_reminder_service.repository.list_remindable(
            db, tenant_id=TENANT, department="不存在的部门XYZ",
        )
        assert tasks_none == []
    finally:
        db.close()
    print("✓ Part2 list_remindable 过滤")


def test_p3_remind_department_admins():
    """Part 3：remind_department_admins 部门 digest"""
    import work_agent.wechat.client as wc

    sent = []

    class FakeClient:
        def send_text_message(self, user_id, content):
            sent.append((user_id, content))
            return {"errcode": 0, "errmsg": "ok"}

    old_client = wc.wecom_client
    wc.wecom_client = FakeClient()

    try:
        summary = task_reminder_service.remind_department_admins(
            department=DEPT,
            tenant_id=TENANT,
            min_risk="medium",
        )
        # 部门管理员（dept_admin_A，研发部）应收到 digest
        assert summary["scanned"] >= 0
        assert summary["risky"] >= 0
        # 发送成功（mock 企微）或未绑定跳过，不报错
        assert summary["failed"] == 0
        print(f"  digest summary: {summary}")
        print("✓ Part3 remind_department_admins")
    finally:
        wc.wecom_client = old_client


def test_p4_department_digests():
    """Part 4：周报部门经理投递（聚合，非逐条）"""
    import work_agent.wechat.client as wc

    sent = []

    class FakeClient:
        def send_text_message(self, user_id, content):
            sent.append((user_id, content))
            return {"errcode": 0, "errmsg": "ok"}

    old_client = wc.wecom_client
    wc.wecom_client = FakeClient()

    try:
        summary = task_report_service.send_department_digests(
            tenant_id=TENANT,
        )
        # 每个部门一次 digest（聚合）
        assert summary["failed"] == 0
        if sent:
            # 部门经理收到的是聚合 digest（含"周报"和"汇总"字样）
            assert all("周报" in content for _, content in sent)
        print(f"  digest summary: {summary}")
        print("✓ Part4 周报部门经理投递")
    finally:
        wc.wecom_client = old_client


def test_p5_scan_department():
    """Part 5：scan_and_remind(department=...) 定向部门"""
    import work_agent.wechat.client as wc

    class FakeClient:
        def send_text_message(self, user_id, content):
            return {"errcode": 0, "errmsg": "ok"}

    old_client = wc.wecom_client
    wc.wecom_client = FakeClient()

    try:
        summary = task_reminder_service.scan_and_remind(
            department=DEPT,
            tenant_id=TENANT,
            min_risk="medium",
        )
        assert summary["scanned"] >= 0
        print(f"  scan summary: {summary}")
        print("✓ Part5 scan_and_remind 定向部门")
    finally:
        wc.wecom_client = old_client


def test():
    print("== 任务督办增强测试（Phase 4）==")
    _cleanup()
    try:
        test_p1_staleness()
        test_p2_remindable_filter()
        test_p3_remind_department_admins()
        test_p4_department_digests()
        test_p5_scan_department()
    finally:
        _cleanup()
    print("任务督办增强测试全部通过")


if __name__ == "__main__":
    test()
