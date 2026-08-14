"""
统一通知服务

- 企业微信（当前）
- 邮件 / 系统消息（预留）

所有通知落库 task_notifications，失败不影响业务主流程
"""

from datetime import datetime

from work_agent.db.models.task import TaskNotification
from work_agent.db.session import SessionLocal


class NotificationService:

    def record(
            self,
            *,
            tenant_id: str,
            task_id: int,
            receiver_id: int,
            channel: str = "wechat",
            content: str,
            status: str = "pending",
            sent_at: datetime | None = None
    ) -> TaskNotification:

        """
        记录一条通知（pending/sent/failed）
        """

        db = SessionLocal()

        try:

            notification = TaskNotification(
                tenant_id=tenant_id,
                task_id=task_id,
                receiver_id=receiver_id,
                channel=channel,
                content=content,
                status=status,
                sent_at=sent_at,
            )

            db.add(notification)

            db.commit()

            db.refresh(notification)

            return notification

        finally:

            db.close()

    def send_wechat(
            self,
            *,
            tenant_id: str,
            task_id: int,
            receiver_id: int,
            wechat_user_id: str,
            content: str
    ) -> dict:

        """
        发送企微消息并记录状态；任何异常都吞掉，不影响调用方
        """

        try:

            from work_agent.wechat.client import wecom_client

            resp = wecom_client.send_text_message(
                wechat_user_id,
                content,
            )

            ok = (
                resp.get("errcode") == 0
            )

            status = (
                "sent"
                if ok
                else "failed"
            )

            detail = str(
                resp.get("errmsg")
                or ""
            )

        except Exception as exc:

            ok = False

            status = "failed"

            detail = str(exc)

        self.record(
            tenant_id=tenant_id,
            task_id=task_id,
            receiver_id=receiver_id,
            channel="wechat",
            content=content,
            status=status,
            sent_at=(
                datetime.now()
                if ok
                else None
            ),
        )

        return {
            "ok": ok,
            "status": status,
            "detail": detail,
        }

    def send_task_created(
            self,
            task
    ) -> dict:

        """
        任务创建后通知负责人（企微主动推送）

        失败不影响任务创建（内部吞异常 + 落库 failed）
        """

        from work_agent.repositories.user_repository import UserRepository

        db = SessionLocal()

        try:

            employee = UserRepository().get_by_id(
                db,
                task.employee_id,
            )

            content = self._task_created_text(task)

            if not employee or not employee.wechat_user_id:

                self.record(
                    tenant_id=task.tenant_id,
                    task_id=task.id,
                    receiver_id=task.employee_id,
                    channel="wechat",
                    content=content,
                    status="failed",
                )

                return {
                    "ok": False,
                    "status": "failed",
                    "detail": "员工未绑定企微",
                }

            return self.send_wechat(
                tenant_id=task.tenant_id,
                task_id=task.id,
                receiver_id=task.employee_id,
                wechat_user_id=employee.wechat_user_id,
                content=content,
            )

        finally:

            db.close()

    def send_task_completed_email(
            self,
            task
    ) -> dict:

        """
        任务完成邮件通知（收件人：创建者 + 主管，Phase 4）

        EMAIL_ENABLED=false → 跳过不记录（避免噪音）
        开启但收件人无邮箱 → 记 failed（channel=email）
        """

        from work_agent.config import settings

        from work_agent.services.email_service import email_service

        if not settings.email_enabled:

            return {
                "ok": False,
                "status": "skipped",
                "detail": "邮件未配置",
            }

        receiver_ids = {
            task.creator_id,
            task.manager_id,
        } - {None}

        if not receiver_ids:

            return {
                "ok": False,
                "status": "skipped",
                "detail": "无收件人（创建者/主管）",
            }

        from work_agent.repositories.user_repository import UserRepository

        db = SessionLocal()

        try:

            repo = UserRepository()

            recipients = []

            for uid in receiver_ids:

                user = repo.get_by_id(
                    db,
                    uid,
                )

                if user and user.email:

                    recipients.append(
                        user
                    )

        finally:

            db.close()

        if not recipients:

            self.record(
                tenant_id=task.tenant_id,
                task_id=task.id,
                receiver_id=task.creator_id or 0,
                channel="email",
                content="任务完成通知（收件人无邮箱）",
                status="failed",
            )

            return {
                "ok": False,
                "status": "failed",
                "detail": "收件人无邮箱",
            }

        content = self._task_completed_email_text(
            task,
            completed_at=datetime.now(),
        )

        ok_all = True

        detail = ""

        for user in recipients:

            result = email_service.send(
                to=user.email,
                subject="员工任务完成通知",
                content=content,
            )

            self.record(
                tenant_id=task.tenant_id,
                task_id=task.id,
                receiver_id=user.id,
                channel="email",
                content=content,
                status=result["status"],
                sent_at=(
                    datetime.now()
                    if result["ok"]
                    else None
                ),
            )

            if not result["ok"]:

                ok_all = False

                detail = result.get(
                    "detail",
                    "",
                )

        return {
            "ok": ok_all,
            "status": (
                "sent"
                if ok_all
                else "failed"
            ),
            "detail": detail,
        }

    @staticmethod
    def _task_completed_email_text(
            task,
            *,
            completed_at
    ) -> str:

        lines = [
            "员工任务完成通知",
            "",
            f"任务：{task.title}",
            f"完成度：{task.progress}%",
            f"完成时间：{completed_at.strftime('%Y-%m-%d %H:%M')}",
        ]

        return "\n".join(lines)

    @staticmethod
    def _task_created_text(
            task
    ) -> str:

        lines = [
            "您有一个新任务：",
            "",
            f"任务名称：{task.title}",
        ]

        if task.description:

            lines.append(
                f"任务描述：{task.description}"
            )

        if task.deadline:

            lines.append(
                "截止时间："
                + task.deadline.strftime("%Y-%m-%d %H:%M")
            )

        lines.append(
            f"优先级：{task.priority}"
        )

        lines.append("")
        lines.append("请及时处理。回复「我的任务」查看")

        return "\n".join(lines)


# 全局单例
notification_service = NotificationService()
