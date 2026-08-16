"""
任务督办定时调度（Phase 3）

APScheduler BackgroundScheduler：每天按 TASK_REMINDER_TIME 触发一次
scan_and_remind（企微提醒任务负责人）。

- 进程内调度：Dockerfile 单 worker，无重复执行风险
- 受 TASK_REMINDER_ENABLED 控制（默认关，测试 / TestClient 不会误启动定时器）
- 定时器逻辑（CronTrigger）不进测试；测试只测核心函数与启动 no-op

用法：
    python -m work_agent.scheduler.task_scheduler             # 手动跑一次（真发送）
    python -m work_agent.scheduler.task_scheduler --dry-run   # 手动跑一次（只统计，不发）
"""

import logging
import sys

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from work_agent.config import settings
from work_agent.services.email_service import email_service
from work_agent.services.task_reminder_service import task_reminder_service
from work_agent.services.task_report_service import task_report_service


logger = logging.getLogger("work_agent.scheduler")

# 进程内调度器持有者（幂等：重复启动直接返回）
_scheduler: BackgroundScheduler | None = None


def _parse_time(
        value: str
) -> tuple[int, int]:

    """
    "HH:MM" → (hour, minute)；非法回退 (9, 0)
    """

    try:

        hour_text, minute_text = value.split(":")

        hour = int(hour_text)

        minute = int(minute_text)

        if 0 <= hour <= 23 and 0 <= minute <= 59:

            return hour, minute

    except (ValueError, AttributeError):

        pass

    logger.warning(
        "无效的 task_reminder_time=%r，回退 09:00",
        value,
    )

    return 9, 0


def _daily_reminder_job() -> None:

    """
    定时任务：扫描 + 企微提醒（内部吞异常，只记录日志，不中断调度）
    """

    try:

        department = (
            settings.task_reminder_department
            or ""
        )

        summary = task_reminder_service.scan_and_remind(
            min_risk=settings.task_reminder_min_risk,
            department=department,
        )

        logger.info(
            "任务督办提醒完成：%s",
            summary,
        )

        # Enterprise Agent：部门管理员 digest（默认关闭）
        if settings.task_reminder_manager_digest:

            digest = task_reminder_service.remind_department_admins(
                department=department,
                min_risk=settings.task_reminder_min_risk,
            )

            logger.info(
                "部门管理员 digest 完成：%s",
                digest,
            )

    except Exception:

        logger.exception(
            "任务督办提醒失败"
        )


def _weekly_email_text(
        report: dict
) -> str:

    """
    周报摘要 → 邮件纯文本
    """

    lines = [
        "任务周报",
        "",
        (
            f"统计周期：{report['period']['start'][:10]} ~ "
            f"{report['period']['end'][:10]}"
        ),
        "",
    ]

    s = report["summary"]

    lines.append(
        f"本周完成任务：{s['completed_this_week']} 个"
    )

    lines.append(
        f"延期任务：{s['overdue']} 个"
    )

    lines.append(
        f"高风险任务：{s['high_risk']} 个"
    )

    lines.append("")

    lines.append("建议：")

    for tip in report["suggestions"]:

        lines.append(f"- {tip}")

    return "\n".join(lines)


def _weekly_report_job() -> None:

    """
    每周汇总周报：生成 Word → 邮件发送给配置收件人（失败只记日志）
    """

    try:

        result = task_report_service.generate_weekly()

        report = result["summary"]

        logger.info(
            "周报生成完成：%s",
            report["summary"],
        )

        recipients = [
            email.strip()
            for email in settings.weekly_report_emails.split(",")
            if email.strip()
        ]

        if not recipients:

            logger.info(
                "周报未配置收件人（WEEKLY_REPORT_EMAILS），跳过邮件发送"
            )

            return

        text = _weekly_email_text(report)

        for to in recipients:

            outcome = email_service.send(
                to=to,
                subject="任务周报",
                content=text,
            )

            logger.info(
                "周报邮件 to=%s status=%s",
                to,
                outcome["status"],
            )

        # Enterprise Agent：周报部门经理 digest（默认关闭）
        if settings.weekly_report_manager_digest:

            digests = task_report_service.send_department_digests()

            logger.info(
                "周报部门经理 digest 完成：%s",
                digests,
            )

    except Exception:

        logger.exception(
            "周报生成/发送失败"
        )


def start_scheduler() -> BackgroundScheduler | None:

    """
    启动每日督办 + 每周周报调度；均未启用时 no-op 返回 None
    """

    global _scheduler

    if (
        _scheduler is not None
        and _scheduler.running
    ):

        return _scheduler

    if not (
        settings.task_reminder_enabled
        or settings.weekly_report_enabled
    ):

        logger.info(
            "任务调度未启用（TASK_REMINDER_ENABLED / WEEKLY_REPORT_ENABLED 均关闭）"
        )

        return None

    scheduler = BackgroundScheduler()

    if settings.task_reminder_enabled:

        hour, minute = _parse_time(
            settings.task_reminder_time,
        )

        scheduler.add_job(
            _daily_reminder_job,
            trigger=CronTrigger(
                hour=hour,
                minute=minute,
            ),
            id="task_daily_reminder",
            coalesce=True,
            max_instances=1,
            misfire_grace_time=3600,
            replace_existing=True,
        )

        logger.info(
            "任务督办调度已启动：每日 %02d:%02d 企微提醒（最低风险 %s）",
            hour,
            minute,
            settings.task_reminder_min_risk,
        )

    if settings.weekly_report_enabled:

        wh, wm = _parse_time(
            settings.weekly_report_time,
        )

        scheduler.add_job(
            _weekly_report_job,
            trigger=CronTrigger(
                day_of_week=(
                    settings.weekly_report_day
                    or "mon"
                ),
                hour=wh,
                minute=wm,
            ),
            id="weekly_report",
            coalesce=True,
            max_instances=1,
            misfire_grace_time=3600,
            replace_existing=True,
        )

        logger.info(
            "任务周报调度已启动：每周 %s %02d:%02d",
            settings.weekly_report_day,
            wh,
            wm,
        )

    scheduler.start()

    _scheduler = scheduler

    return scheduler


def stop_scheduler(
        scheduler: BackgroundScheduler | None = None
) -> None:

    """
    停止调度器（wait=False，不阻塞应用关闭）
    """

    global _scheduler

    target = scheduler or _scheduler

    if target is not None and target.running:

        target.shutdown(wait=False)

        logger.info("任务督办调度已停止")

    _scheduler = None


def run_reminder_now(
        *,
        dry_run: bool = False
) -> dict:

    """
    手动跑一次（默认发真实企微；dry_run 只统计）
    """

    return task_reminder_service.scan_and_remind(
        min_risk=settings.task_reminder_min_risk,
        dry_run=dry_run,
    )


if __name__ == "__main__":

    dry_run = "--dry-run" in sys.argv

    summary = run_reminder_now(
        dry_run=dry_run,
    )

    tag = "（DRY-RUN 未发送）" if dry_run else ""

    print(
        f"任务督办{tag} 摘要：{summary}"
    )
