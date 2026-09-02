"""
任务自动督办服务（Phase 3）

每天定时扫描未完成任务 → 按截止日期 + 进度判断风险（确定性规则）→
企微主动提醒任务负责人（员工）。

- 风险规则确定性、可单测，无 LLM 依赖（每日定时任务零成本、零失败）
- 仅提醒员工（按 docs/phase-6-2-task-supervision.md Phase 3 设计）
- 发送复用 notification_service.send_wechat（发送 + 落库 task_notifications，
  任何异常吞掉不影响主流程）；未绑定企微的员工记录 failed 不发送
- 多租户：通知按 task.tenant_id 隔离

用法：
    python -m work_agent.scheduler.task_scheduler --dry-run   # 安全手验
"""

import math

from datetime import datetime

from work_agent.db.models import User
from work_agent.db.session import SessionLocal
from work_agent.repositories.task_repository import TaskRepository
from work_agent.repositories.user_repository import UserRepository
from work_agent.services.notification_service import notification_service


# 达到该等级及以上的任务才提醒
_REMIND_LEVELS = {
    "high": {"high"},
    "medium": {"medium", "high"},
    "low": {"low", "medium", "high"},
}

_RISK_NAMES = {
    "high": "高",
    "medium": "中",
    "low": "低",
}


class TaskReminderService:

    def __init__(
            self,
            repository: TaskRepository | None = None,
            user_repository: UserRepository | None = None
    ):

        self.repository = repository or TaskRepository()

        self.user_repository = user_repository or UserRepository()

    # ======================
    # 风险判断（确定性规则）
    # ======================

    def compute_risk(
            self,
            task,
            now: datetime | None = None
    ) -> dict:

        """
        按截止日期 + 进度判断风险等级

        规则（docs/phase-6-2-task-supervision.md 示例：距截止 7 天完成 20% → 高风险）：
        - 无截止日期    → low
        - 已逾期        → high
        - 剩余 ≤1 天    → 进度<90→high，否则 medium
        - 剩余 ≤3 天    → 进度<70→high，<90→medium，否则 low
        - 剩余 ≤7 天    → 进度<40→high，<70→medium，否则 low
        - 剩余 >7 天    → 进度<20 且优先级高→medium，否则 low

        返回 {level, reason, days_remaining}
        """

        now = now or datetime.now()

        deadline = task.deadline

        if not deadline:

            return {
                "level": "low",
                "reason": "无截止日期",
                "days_remaining": None,
            }

        days_remaining = (
            deadline - now
        ).total_seconds() / 86400.0

        progress = task.progress or 0

        if days_remaining < 0:

            overdue_days = max(
                1,
                int(math.ceil(-days_remaining)),
            )

            return {
                "level": "high",
                "reason": f"已逾期 {overdue_days} 天",
                "days_remaining": round(
                    days_remaining,
                    1,
                ),
            }

        if days_remaining <= 1:

            return self._risk_result(
                progress,
                high_below=90,
                medium_below=100,
                days_remaining=days_remaining,
            )

        if days_remaining <= 3:

            return self._risk_result(
                progress,
                high_below=70,
                medium_below=90,
                days_remaining=days_remaining,
            )

        if days_remaining <= 7:

            return self._risk_result(
                progress,
                high_below=40,
                medium_below=70,
                days_remaining=days_remaining,
            )

        # 剩余超过 7 天
        if progress < 20 and task.priority == "high":

            return {
                "level": "medium",
                "reason": (
                    f"距截止还有 {int(math.floor(days_remaining))} 天，"
                    "完成进度偏低"
                ),
                "days_remaining": round(
                    days_remaining,
                    1,
                ),
            }

        return {
            "level": "low",
            "reason": (
                f"距截止还有 {int(math.floor(days_remaining))} 天，进度正常"
            ),
            "days_remaining": round(
                days_remaining,
                1,
            ),
        }

    @staticmethod
    def _risk_result(
            progress: int,
            *,
            high_below: int,
            medium_below: int,
            days_remaining: float
    ) -> dict:

        if progress < high_below:

            level = "high"

        elif progress < medium_below:

            level = "medium"

        else:

            level = "low"

        return {
            "level": level,
            "reason": (
                f"距截止还有 {int(math.floor(days_remaining))} 天，"
                f"当前进度 {progress}%"
            ),
            "days_remaining": round(
                days_remaining,
                1,
            ),
        }

    # ======================
    # 提醒文案
    # ======================

    @staticmethod
    def build_reminder_text(
            task,
            risk: dict
    ) -> str:

        """
        模板文案（对齐 notification_service._task_created_text 风格）
        """

        lines = [
            "任务督办提醒：",
            "",
            f"任务名称：{task.title}",
            f"当前进度：{task.progress}%",
        ]

        if task.deadline:

            lines.append(
                "截止时间："
                + task.deadline.strftime("%Y-%m-%d %H:%M")
            )

        level = risk.get("level", "low")

        reason = risk.get("reason", "")

        if reason:

            lines.append(
                f"风险：{_RISK_NAMES.get(level, level)}（{reason}）"
            )

        lines.append("")
        lines.append(
            f"请及时推进。回复「提交{task.title} 完成XX%」汇报进展，"
            "或「我的任务」查看。"
        )

        return "\n".join(lines)

    # ======================
    # 每日扫描 + 提醒
    # ======================

    def scan_and_remind(
            self,
            now: datetime | None = None,
            min_risk: str = "medium",
            dry_run: bool = False,
            tenant_id: str | None = None,
            department: str = ""
    ) -> dict:

        """
        每日督办核心：扫描未完成含截止任务 → 判断风险 →
        达到阈值则企微提醒员工。

        tenant_id / department 可选定向（Enterprise Agent Phase 4）。
        dry_run=True 只统计不发送不落库（安全手验）。

        返回：
        {scanned, low, medium, high, reminded, skipped_unbound, failed}
        """

        now = now or datetime.now()

        remind_levels = _REMIND_LEVELS.get(
            min_risk,
            {"medium", "high"},
        )

        summary = {
            "scanned": 0,
            "low": 0,
            "medium": 0,
            "high": 0,
            "reminded": 0,
            "skipped_unbound": 0,
            "failed": 0,
        }

        db = SessionLocal()

        try:

            tasks = self.repository.list_remindable(
                db,
                tenant_id=tenant_id,
                department=department,
            )

            summary["scanned"] = len(tasks)

            for task in tasks:

                risk = self.compute_risk(
                    task,
                    now=now,
                )

                level = risk["level"]

                summary[level] = summary.get(level, 0) + 1

                if level not in remind_levels:

                    continue

                employee = self.user_repository.get_by_id(
                    db,
                    task.employee_id,
                )

                content = self.build_reminder_text(
                    task,
                    risk,
                )

                if not employee or not employee.wechat_user_id:

                    # 未绑定企微：对齐 send_task_created 记 failed，不阻塞
                    if not dry_run:

                        notification_service.record(
                            tenant_id=task.tenant_id,
                            task_id=task.id,
                            receiver_id=task.employee_id,
                            channel="wechat",
                            content=content,
                            status="failed",
                        )

                    summary["skipped_unbound"] += 1

                    continue

                if dry_run:

                    summary["reminded"] += 1

                    continue

                result = notification_service.send_wechat(
                    tenant_id=task.tenant_id,
                    task_id=task.id,
                    receiver_id=task.employee_id,
                    wechat_user_id=employee.wechat_user_id,
                    content=content,
                )

                if result.get("ok"):

                    summary["reminded"] += 1

                else:

                    summary["failed"] += 1

            return summary

        finally:

            db.close()

    # ======================
    # 部门管理员督办摘要（Enterprise Agent Phase 4）
    # ======================

    @staticmethod
    def compute_staleness(
            task,
            now: datetime | None = None
    ) -> int:

        """
        计算任务已停滞天数（确定性，无 LLM）

        规则：status∈{pending,processing} 且含截止，且 updated_at 距今 >3 天
        才视为停滞；返回天数（否则 0）。仅用于摘要文案「N 天未更新」，
        不影响 compute_risk（避免回归 test_task_reminder Part1）。
        """

        from datetime import timedelta

        now = now or datetime.now()

        if task.status not in ("pending", "processing"):

            return 0

        if not task.deadline:

            return 0

        updated = task.updated_at or task.created_at

        if not updated:

            return 0

        days = (
            now - updated
        ).total_seconds() / 86400.0

        if days <= 3:

            return 0

        return max(1, int(days))

    @staticmethod
    def build_digest_text(
            department: str,
            risky: list,
            now: datetime | None = None
    ) -> str:

        """
        部门高风险任务摘要（发给部门经理，非逐条推送）
        """

        now = now or datetime.now()

        if not risky:

            return f"{department or '本部门'}当前无高风险任务。"

        lines = [
            f"{department or '本部门'}重点关注任务（{len(risky)}项）：",
            "",
        ]

        for task, risk in risky:

            lines.append(
                f"- {task.title}"
                f"（进度{task.progress}%，"
                f"截止{task.deadline.strftime('%m月%d日') if task.deadline else '未定'}"
                f"，{risk['reason']}）"
            )

        return "\n".join(lines)

    def remind_department_admins(
            self,
            department: str = "",
            tenant_id: str | None = None,
            min_risk: str = "medium",
            dry_run: bool = False,
            now: datetime | None = None
    ) -> dict:

        """
        聚合部门高风险任务 → 企微 digest 发给部门管理员（DEPARTMENT_ADMIN）

        多租户铁律：按 tenant_id 过滤；部门管理员按 user.department 字符串匹配
        （TODO(Enterprise)：后续 department_id 外键后改关联查询）。

        返回：
        {scanned, risky, reminded, skipped_unbound, failed}
        """

        now = now or datetime.now()

        remind_levels = _REMIND_LEVELS.get(
            min_risk,
            {"medium", "high"},
        )

        summary = {
            "scanned": 0,
            "risky": 0,
            "reminded": 0,
            "skipped_unbound": 0,
            "failed": 0,
        }

        db = SessionLocal()

        try:

            # 1. 扫描任务（按租户/部门）
            tasks = self.repository.list_remindable(
                db,
                tenant_id=tenant_id,
                department=department,
            )

            summary["scanned"] = len(tasks)

            risky = []

            for task in tasks:

                risk = self.compute_risk(
                    task,
                    now=now,
                )

                level = risk["level"]

                if level in remind_levels:

                    risky.append((task, risk))

            summary["risky"] = len(risky)

            if not risky:

                return summary

            # 2. 找部门管理员（DEPARTMENT_ADMIN，department 匹配）
            admins = self._department_admins(
                db,
                department=department or "",
                tenant_id=tenant_id or "",
            )

            if not admins:

                return summary

            content = self.build_digest_text(
                department or "本部门",
                risky,
                now=now,
            )

            # 3. 逐个发送 digest（同内容，非逐条任务推送）
            for admin in admins:

                if not admin.wechat_user_id:

                    if not dry_run:

                        notification_service.record(
                            tenant_id=(
                                admin.tenant_id
                                or tenant_id
                                or ""
                            ),
                            task_id=0,
                            receiver_id=admin.id,
                            channel="wechat",
                            content=content,
                            status="failed",
                        )

                    summary["skipped_unbound"] += 1

                    continue

                if dry_run:

                    summary["reminded"] += 1

                    continue

                result = notification_service.send_wechat(
                    tenant_id=(
                        admin.tenant_id
                        or tenant_id
                        or ""
                    ),
                    task_id=0,
                    receiver_id=admin.id,
                    wechat_user_id=admin.wechat_user_id,
                    content=content,
                )

                if result.get("ok"):

                    summary["reminded"] += 1

                else:

                    summary["failed"] += 1

            return summary

        finally:

            db.close()

    def _department_admins(
            self,
            db,
            department: str,
            tenant_id: str = ""
    ):

        """
        查询部门管理员用户（DEPARTMENT_ADMIN 角色，department 匹配）

        经 RBACRepository.list_user_ids_by_role + UserRepository。
        """

        from work_agent.repositories.rbac_repository import RBACRepository

        user_ids = RBACRepository().list_user_ids_by_role(
            db,
            "DEPARTMENT_ADMIN",
        )

        if not user_ids:

            return []

        query = db.query(User).filter(
            User.id.in_(user_ids),
        )

        if department:

            query = query.filter(
                User.department == department,
            )

        if tenant_id:

            query = query.filter(
                User.tenant_id == tenant_id,
            )

        return query.all()


# 全局单例
task_reminder_service = TaskReminderService()
