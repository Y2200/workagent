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


# 全局单例
notification_service = NotificationService()
