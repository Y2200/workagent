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
from work_agent.services.task_reminder_service import task_reminder_service


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

        summary = task_reminder_service.scan_and_remind(
            min_risk=settings.task_reminder_min_risk,
        )

        logger.info(
            "任务督办提醒完成：%s",
            summary,
        )

    except Exception:

        logger.exception(
            "任务督办提醒失败"
        )


def start_scheduler() -> BackgroundScheduler | None:

    """
    启动每日督办调度；未启用时 no-op 返回 None（保证测试不误启动）
    """

    global _scheduler

    if (
        _scheduler is not None
        and _scheduler.running
    ):

        return _scheduler

    if not settings.task_reminder_enabled:

        logger.info(
            "任务督办调度未启用（TASK_REMINDER_ENABLED=false）"
        )

        return None

    hour, minute = _parse_time(
        settings.task_reminder_time,
    )

    scheduler = BackgroundScheduler()

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

    scheduler.start()

    _scheduler = scheduler

    logger.info(
        "任务督办调度已启动：每日 %02d:%02d 企微提醒（最低风险 %s）",
        hour,
        minute,
        settings.task_reminder_min_risk,
    )

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
