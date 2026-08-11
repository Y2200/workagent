from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from work_agent.db.models import OperationLog


class OperationLogRepository:

    """
    操作审计日志数据访问
    """

    def create(
            self,
            db: Session,
            *,
            tenant_id: str,
            action: str,
            user_id: int | None = None,
            target_type: str | None = None,
            target_id: str | None = None,
            ip: str | None = None,
            user_agent: str | None = None
    ) -> OperationLog:

        log = OperationLog(
            tenant_id=tenant_id,
            user_id=user_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            ip=ip,
            user_agent=user_agent,
        )

        db.add(log)

        db.commit()

        db.refresh(log)

        return log


    def list(
            self,
            db: Session,
            *,
            tenant_id: str,
            action: str | None = None,
            user_id: int | None = None,
            start_time: datetime | None = None,
            end_time: datetime | None = None,
            offset: int = 0,
            limit: int = 20
    ):

        query = (
            db.query(OperationLog)
            .filter(OperationLog.tenant_id == tenant_id)
        )

        if action:
            query = query.filter(
                OperationLog.action == action
            )

        if user_id is not None:
            query = query.filter(
                OperationLog.user_id == user_id
            )

        if start_time is not None:
            query = query.filter(
                OperationLog.created_at >= start_time
            )

        if end_time is not None:
            query = query.filter(
                OperationLog.created_at <= end_time
            )

        return (
            query
            .order_by(OperationLog.id.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )


    def count(
            self,
            db: Session,
            *,
            tenant_id: str,
            action: str | None = None,
            user_id: int | None = None,
            start_time: datetime | None = None,
            end_time: datetime | None = None
    ) -> int:

        query = (
            db.query(func.count(OperationLog.id))
            .filter(OperationLog.tenant_id == tenant_id)
        )

        if action:
            query = query.filter(
                OperationLog.action == action
            )

        if user_id is not None:
            query = query.filter(
                OperationLog.user_id == user_id
            )

        if start_time is not None:
            query = query.filter(
                OperationLog.created_at >= start_time
            )

        if end_time is not None:
            query = query.filter(
                OperationLog.created_at <= end_time
            )

        return int(query.scalar() or 0)
