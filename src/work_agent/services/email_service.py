"""
统一邮件服务（Phase 4）

- SMTP 发送（SSL 465 / STARTTLS 其他端口），任何异常吞掉不影响调用方
- EMAIL_ENABLED=false 或 SMTP 未配置 → {ok:False, status:"skipped"}（静默跳过）
- 发送状态由上层（NotificationService / 周报）落库 task_notifications

用法：
    from work_agent.services.email_service import email_service
    email_service.send(to="a@x.com", subject="任务完成", content="...")
"""

import logging
import smtplib

from email.header import Header
from email.mime.text import MIMEText
from email.utils import formataddr

from work_agent.config import settings


logger = logging.getLogger(__name__)


class EmailService:

    def _is_configured(self) -> bool:

        return (
            settings.email_enabled
            and bool(settings.smtp_host)
            and bool(settings.smtp_from or settings.smtp_username)
        )

    def send(
            self,
            *,
            to: str,
            subject: str,
            content: str
    ) -> dict:

        """
        发送一封纯文本邮件；任何失败都返回 failed，不抛异常
        """

        if not self._is_configured():

            return {
                "ok": False,
                "status": "skipped",
                "detail": "邮件未配置",
            }

        from_addr = (
            settings.smtp_from
            or settings.smtp_username
        )

        try:

            message = MIMEText(
                content,
                "plain",
                "utf-8",
            )

            message["Subject"] = Header(
                subject,
                "utf-8",
            )

            message["From"] = formataddr(
                ("Work Agent", from_addr)
            )

            message["To"] = to

            if settings.smtp_port == 465:

                server = smtplib.SMTP_SSL(
                    settings.smtp_host,
                    settings.smtp_port,
                    timeout=15,
                )

            else:

                server = smtplib.SMTP(
                    settings.smtp_host,
                    settings.smtp_port,
                    timeout=15,
                )

                server.starttls()

            try:

                if settings.smtp_username:

                    server.login(
                        settings.smtp_username,
                        settings.smtp_password,
                    )

                server.sendmail(
                    from_addr,
                    [to],
                    message.as_string(),
                )

            finally:

                server.quit()

            return {
                "ok": True,
                "status": "sent",
                "detail": "",
            }

        except Exception as exc:

            logger.warning(
                "邮件发送失败 to=%s: %s",
                to,
                exc,
            )

            return {
                "ok": False,
                "status": "failed",
                "detail": str(exc),
            }


# 全局单例
email_service = EmailService()
