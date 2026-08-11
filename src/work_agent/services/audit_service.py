from datetime import date, datetime, time, timedelta

from sqlalchemy.orm import Session

from work_agent.config import settings
from work_agent.db.models import User
from work_agent.db.session import SessionLocal
from work_agent.repositories.agent_log_repository import AgentLogRepository
from work_agent.repositories.operation_log_repository import OperationLogRepository


class AuditService:

    """
    审计日志服务（租户隔离查询）

    统一承载：
    - 问答审计（agent_logs）
    - 操作审计（operation_logs）
    """

    def __init__(
            self,
            repository: AgentLogRepository | None = None,
            operation_repository: OperationLogRepository | None = None
    ):

        self.repository = repository or AgentLogRepository()

        self.operation_repository = operation_repository or OperationLogRepository()


    def list_logs(
            self,
            *,
            tenant_id: str,
            user_id: int | None = None,
            channel: str | None = None,
            status: str | None = None,
            start_time: datetime | None = None,
            end_time: datetime | None = None,
            page: int = 1,
            page_size: int = 20,
            include_archived: bool = False
    ) -> dict:

        """
        按租户隔离查询日志，返回分页结构
        """

        start_time = _naive(start_time)

        end_time = _naive(end_time)

        offset = (page - 1) * page_size

        db = SessionLocal()

        try:

            items = self.repository.list(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
                channel=channel,
                status=status,
                start_time=start_time,
                end_time=end_time,
                offset=offset,
                limit=page_size,
                include_archived=include_archived,
            )

            total = self.repository.count(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
                channel=channel,
                status=status,
                start_time=start_time,
                end_time=end_time,
                include_archived=include_archived,
            )

            self._attach_usernames(
                db,
                items
            )

            return {
                "items": items,
                "total": total,
                "page": page,
                "page_size": page_size,
            }

        finally:

            db.close()


    def _attach_usernames(
            self,
            db: Session,
            items
    ) -> None:

        """
        批量回填 username，便于前端展示
        """

        user_ids = {
            item.user_id
            for item in items
            if item.user_id
        }

        if not user_ids:
            return

        rows = (
            db.query(User.id, User.username)
            .filter(User.id.in_(user_ids))
            .all()
        )

        name_map = {
            user_id: username
            for user_id, username in rows
        }

        for item in items:
            item.username = name_map.get(
                item.user_id
            )


    def get_statistics(
            self,
            tenant_id: str
    ) -> dict:

        """
        审计统计（租户隔离）
        """

        today_start = datetime.combine(
            date.today(),
            time.min
        )

        db = SessionLocal()

        try:

            return self.repository.statistics(
                db,
                tenant_id,
                today_start,
            )

        finally:

            db.close()


    def log_operation(
            self,
            *,
            tenant_id: str,
            action: str,
            user_id: int | None = None,
            target_type: str | None = None,
            target_id: str | None = None,
            ip: str | None = None,
            user_agent: str | None = None
    ) -> None:

        """
        记录企业操作（登录/上传/删除/改权限/导出等）

        业务层只调用本方法，不散落日志逻辑
        """

        db = SessionLocal()

        try:

            self.operation_repository.create(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
                action=action,
                target_type=target_type,
                target_id=target_id,
                ip=ip,
                user_agent=user_agent,
            )

        finally:

            db.close()


    def list_operations(
            self,
            *,
            tenant_id: str,
            action: str | None = None,
            user_id: int | None = None,
            start_time: datetime | None = None,
            end_time: datetime | None = None,
            page: int = 1,
            page_size: int = 20
    ) -> dict:

        """
        操作审计列表（租户隔离）
        """

        start_time = _naive(start_time)

        end_time = _naive(end_time)

        offset = (page - 1) * page_size

        db = SessionLocal()

        try:

            items = self.operation_repository.list(
                db,
                tenant_id=tenant_id,
                action=action,
                user_id=user_id,
                start_time=start_time,
                end_time=end_time,
                offset=offset,
                limit=page_size,
            )

            total = self.operation_repository.count(
                db,
                tenant_id=tenant_id,
                action=action,
                user_id=user_id,
                start_time=start_time,
                end_time=end_time,
            )

            self._attach_usernames(
                db,
                items
            )

            return {
                "items": items,
                "total": total,
                "page": page,
                "page_size": page_size,
            }

        finally:

            db.close()


    def archive_expired(
            self,
            tenant_id: str
    ) -> dict:

        """
        归档当前租户过期日志（只标记，不删除）

        保留审计追踪
        """

        cutoff = (
            datetime.now()
            - timedelta(
                days=settings.audit_log_retention_days
            )
        )

        db = SessionLocal()

        try:

            archived_count = self.repository.archive_expired(
                db,
                tenant_id,
                cutoff,
            )

            return {
                "archived_count": archived_count,
            }

        finally:

            db.close()


def _naive(dt: datetime | None):

    """
    created_at 为 naive 本地时间，剥离 tzinfo 以便比较
    """

    if dt is not None and dt.tzinfo:
        return dt.replace(tzinfo=None)

    return dt
