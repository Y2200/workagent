"""
任务自动督办测试套件（Phase 3）

Part 1  风险判断（compute_risk 确定性规则，含 6-2 示例）
Part 2  提醒文案（build_reminder_text 模板字段）
Part 3  督办扫描（list_remindable：只含未完成 + 有截止日期的任务）
Part 4  每日扫描提醒（scan_and_remind：只提醒达到阈值的任务，落库 sent）
Part 5  未绑定企微（记录 failed，不发送）
Part 6  风险阈值（min_risk 过滤）
Part 7  调度接线（enabled=false → no-op；时间解析回退）

用法：
    python -m work_agent.scripts.test_task_reminder
"""

from datetime import datetime, timedelta

from work_agent.db.models import User
from work_agent.db.models.task import (
    Task,
    TaskNotification,
    TaskPendingUpdate,
    TaskUpdate,
)
from work_agent.db.session import SessionLocal
from work_agent.repositories.user_repository import UserRepository
from work_agent.services.auth_service import AuthService
from work_agent.services.task_reminder_service import task_reminder_service
from work_agent.scripts.migrate_tasks import migrate


_TEST_USERS = [
    "督办测试员工",
    "督办测试未绑定",
]


class _FakeTask:

    """
    轻量任务桩（compute_risk / build_reminder_text 不依赖 DB）
    """

    def __init__(
            self,
            title="",
            deadline=None,
            progress=0,
            priority="normal"
    ):

        self.title = title

        self.deadline = deadline

        self.progress = progress

        self.priority = priority


class _FakeRepo:

    """
    限定扫描范围（只返回本测试构造的任务，保证确定性）
    """

    def __init__(
            self,
            tasks
    ):

        self.tasks = tasks

    def list_remindable(
            self,
            db,
            tenant_id=None,
            department=""
    ):

        return self.tasks


def _setup():

    migrate()

    _cleanup()


def _cleanup() -> None:

    """
    清理本套件测试用户及其任务/通知，保证可重复运行
    """

    db = SessionLocal()

    try:

        users = [
            UserRepository().get_by_username(db, name)
            for name in _TEST_USERS
        ]

        ids = [
            u.id
            for u in users
            if u
        ]

        if ids:

            db.query(TaskNotification).filter(
                TaskNotification.receiver_id.in_(ids)
            ).delete(
                synchronize_session=False
            )

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

        for user in users:

            if user:

                db.delete(user)

        db.commit()

    finally:

        db.close()


def _user(
        username: str,
        *,
        bind_wechat: bool = True
):

    db = SessionLocal()

    try:

        user = UserRepository().get_by_username(
            db,
            username,
        )

        if not user:

            user = UserRepository().create(
                db,
                username=username,
                password_hash=AuthService.hash_password("test123"),
                department="研发部",
                role="员工",
                tenant_id="1",
            )

            if bind_wechat:

                user.wechat_user_id = f"wx_{username}"

                db.commit()

                db.refresh(user)

        return user

    finally:

        db.close()


def _make_task(
        employee,
        *,
        title: str,
        deadline=None,
        progress: int = 0,
        priority: str = "normal",
        status: str | None = None
):

    db = SessionLocal()

    try:

        task = Task(
            tenant_id=employee.tenant_id,
            title=title,
            description="",
            creator_id=employee.id,
            employee_id=employee.id,
            department=employee.department,
            deadline=deadline,
            priority=priority,
            status=(
                status
                or ("processing" if progress else "pending")
            ),
            progress=progress,
        )

        db.add(task)

        db.commit()

        db.refresh(task)

        return task

    finally:

        db.close()


def _patch_scan(tasks):

    """
    临时限定扫描范围，返回恢复函数
    """

    real_repo = task_reminder_service.repository

    task_reminder_service.repository = _FakeRepo(tasks)

    def _restore():

        task_reminder_service.repository = real_repo

    return _restore


def _notifications(task_id) -> list:

    db = SessionLocal()

    try:

        return (
            db.query(TaskNotification)
            .filter(TaskNotification.task_id == task_id)
            .all()
        )

    finally:

        db.close()


# ======================
# Part 1 风险判断
# ======================

def test_compute_risk():

    now = datetime(2026, 8, 14, 9, 0)

    # ① 无截止日期 → low
    r = task_reminder_service.compute_risk(
        _FakeTask(deadline=None),
        now=now,
    )

    assert r["level"] == "low", r

    # ② 已逾期 → high
    r = task_reminder_service.compute_risk(
        _FakeTask(
            deadline=now - timedelta(days=2),
            progress=30,
        ),
        now=now,
    )

    assert r["level"] == "high", r

    assert "逾期" in r["reason"], r

    # ③ 6-2 示例：距截止 7 天完成 20% → high
    r = task_reminder_service.compute_risk(
        _FakeTask(
            deadline=now + timedelta(days=7),
            progress=20,
        ),
        now=now,
    )

    assert r["level"] == "high", r

    # ④ 剩余 1 天完成 95% → medium（进度≥90）
    r = task_reminder_service.compute_risk(
        _FakeTask(
            deadline=now + timedelta(days=1),
            progress=95,
        ),
        now=now,
    )

    assert r["level"] == "medium", r

    # ⑤ 剩余 10 天完成 80% → low
    r = task_reminder_service.compute_risk(
        _FakeTask(
            deadline=now + timedelta(days=10),
            progress=80,
        ),
        now=now,
    )

    assert r["level"] == "low", r

    # ⑥ 剩余 10 天完成 10% 且高优先级 → medium
    r = task_reminder_service.compute_risk(
        _FakeTask(
            deadline=now + timedelta(days=10),
            progress=10,
            priority="high",
        ),
        now=now,
    )

    assert r["level"] == "medium", r

    print("Part 1 ✅ 风险判断（确定性规则 + 6-2 示例）")


# ======================
# Part 2 提醒文案
# ======================

def test_build_reminder_text():

    task = _FakeTask(
        title="财务模块开发",
        deadline=datetime(2026, 8, 12, 9, 0),
        progress=30,
    )

    text = task_reminder_service.build_reminder_text(
        task,
        {
            "level": "high",
            "reason": "已逾期 2 天",
            "days_remaining": -2.0,
        },
    )

    assert "任务督办提醒" in text, text

    assert "任务名称：财务模块开发" in text, text

    assert "当前进度：30%" in text, text

    assert "2026-08-12" in text, text

    assert "已逾期 2 天" in text, text

    assert "提交财务模块开发" in text, text

    print("Part 2 ✅ 提醒文案（模板字段齐全）")


# ======================
# Part 3 督办扫描（真实 SQL）
# ======================

def test_list_remindable():

    emp = _user("督办测试员工")

    now = datetime.now()

    # ① 逾期未完成 → 应扫描到
    overdue = _make_task(
        emp,
        title="扫描-逾期",
        deadline=now - timedelta(days=1),
        progress=30,
    )

    # ② 远期低进度未完成 → 应扫描到
    far = _make_task(
        emp,
        title="扫描-远期",
        deadline=now + timedelta(days=10),
        progress=80,
    )

    # ③ 已完成 → 不应扫描到
    _make_task(
        emp,
        title="扫描-已完成",
        deadline=now - timedelta(days=1),
        progress=100,
        status="completed",
    )

    # ④ 无截止日期 → 不应扫描到
    _make_task(
        emp,
        title="扫描-无截止",
        deadline=None,
        progress=10,
    )

    db = SessionLocal()

    try:

        from work_agent.repositories.task_repository import TaskRepository

        rows = TaskRepository().list_remindable(db)

    finally:

        db.close()

    ids = {
        t.id
        for t in rows
    }

    assert overdue.id in ids, ids

    assert far.id in ids, ids

    assert not any(
        t.title == "扫描-已完成"
        for t in rows
    ), "已完成任务不应进入督办扫描"

    assert not any(
        t.title == "扫描-无截止"
        for t in rows
    ), "无截止日期任务不应进入督办扫描"

    print("Part 3 ✅ 督办扫描（只含未完成 + 有截止日期）")


# ======================
# Part 4 每日扫描提醒
# ======================

def test_scan_and_remind():

    import work_agent.wechat.client as wc

    class FakeClient:

        def send_text_message(
                self,
                user_id,
                content,
        ):

            return {
                "errcode": 0,
                "errmsg": "ok",
            }

    wc.wecom_client = FakeClient()

    emp = _user("督办测试员工")

    now = datetime.now()

    high = _make_task(
        emp,
        title="提醒-逾期",
        deadline=now - timedelta(days=2),
        progress=30,
    )

    low = _make_task(
        emp,
        title="提醒-远期",
        deadline=now + timedelta(days=10),
        progress=80,
    )

    restore = _patch_scan([high, low])

    try:

        summary = task_reminder_service.scan_and_remind(
            now=now,
            min_risk="medium",
        )

    finally:

        restore()

    assert summary["scanned"] == 2, summary

    assert summary["high"] == 1, summary

    assert summary["low"] == 1, summary

    # 只提醒达到阈值（medium）的任务 → 只有 high
    assert summary["reminded"] == 1, summary

    rows = _notifications(high.id)

    assert len(rows) == 1, rows

    assert rows[0].status == "sent", rows[0].status

    assert "提醒-逾期" in rows[0].content, rows[0].content

    # low 任务不提醒
    assert _notifications(low.id) == [], "low 风险任务不应被提醒"

    print("Part 4 ✅ 每日扫描提醒（只提醒达到阈值的任务，落库 sent）")


# ======================
# Part 5 未绑定企微
# ======================

def test_unbound_skipped():

    import work_agent.wechat.client as wc

    class CountingClient:

        def __init__(self):

            self.calls = []

        def send_text_message(
                self,
                user_id,
                content,
        ):

            self.calls.append(user_id)

            return {
                "errcode": 0,
                "errmsg": "ok",
            }

    wc.wecom_client = CountingClient()

    emp = _user(
        "督办测试未绑定",
        bind_wechat=False,
    )

    assert not emp.wechat_user_id, "测试前置：员工应未绑定企微"

    now = datetime.now()

    task = _make_task(
        emp,
        title="未绑定-逾期",
        deadline=now - timedelta(days=1),
        progress=50,
    )

    restore = _patch_scan([task])

    try:

        summary = task_reminder_service.scan_and_remind(
            now=now,
        )

    finally:

        restore()

    assert summary["skipped_unbound"] == 1, summary

    assert summary["reminded"] == 0, summary

    assert wc.wecom_client.calls == [], "未绑定员工不应触发企微发送"

    rows = _notifications(task.id)

    assert rows and rows[0].status == "failed", rows

    print("Part 5 ✅ 未绑定企微（记录 failed，不发送）")


# ======================
# Part 6 风险阈值
# ======================

def test_min_risk_threshold():

    import work_agent.wechat.client as wc

    class FakeClient:

        def send_text_message(
                self,
                user_id,
                content,
        ):

            return {
                "errcode": 0,
                "errmsg": "ok",
            }

    wc.wecom_client = FakeClient()

    emp = _user("督办测试员工")

    now = datetime.now()

    high = _make_task(
        emp,
        title="阈值-逾期",
        deadline=now - timedelta(days=1),
        progress=30,
    )

    # 剩余 1 天完成 95% → medium
    medium = _make_task(
        emp,
        title="阈值-临期",
        deadline=now + timedelta(days=1),
        progress=95,
    )

    restore = _patch_scan([high, medium])

    try:

        summary = task_reminder_service.scan_and_remind(
            now=now,
            min_risk="high",
        )

    finally:

        restore()

    assert summary["reminded"] == 1, summary

    assert _notifications(high.id), "high 任务应被提醒"

    assert _notifications(medium.id) == [], "min_risk=high 时 medium 不应被提醒"

    print("Part 6 ✅ 风险阈值（min_risk=high 只发 high）")


# ======================
# Part 7 调度接线
# ======================

def test_scheduler_wiring():

    from work_agent.config import settings

    from work_agent.scheduler.task_scheduler import (
        _parse_time,
        start_scheduler,
    )

    assert _parse_time("09:00") == (9, 0), _parse_time("09:00")

    assert _parse_time("23:59") == (23, 59)

    assert _parse_time("bad") == (9, 0), "非法时间应回退 09:00"

    # enabled=false → no-op（返回 None，不启动定时器线程）
    original = settings.task_reminder_enabled

    settings.task_reminder_enabled = False

    try:

        assert start_scheduler() is None

    finally:

        settings.task_reminder_enabled = original

    print("Part 7 ✅ 调度接线（未启用 no-op / 时间解析回退）")


def test():

    _setup()

    test_compute_risk()

    test_build_reminder_text()

    test_list_remindable()

    test_scan_and_remind()

    test_unbound_skipped()

    test_min_risk_threshold()

    test_scheduler_wiring()


if __name__ == "__main__":

    test()
