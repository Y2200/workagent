from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from work_agent.db.models import AgentLog


class AgentLogRepository:

    """
    Agent 审计日志数据访问
    """

    def create(
            self,
            db: Session,
            *,
            request_id: str,
            tenant_id: str = "",
            user_id: int | None = None,
            department: str = "",
            role: str = "",
            channel: str = "wechat",
            question: str = "",
            status: str = "processing",
            agent_version: str = "",
            model_name: str = ""
    ) -> AgentLog:

        log = AgentLog(
            request_id=request_id,
            tenant_id=tenant_id,
            user_id=user_id,
            department=department,
            role=role,
            channel=channel,
            question=question,
            answer="",
            status=status,
            agent_version=agent_version,
            model_name=model_name,
        )

        db.add(log)

        db.commit()

        db.refresh(log)

        return log


    def complete(
            self,
            db: Session,
            *,
            log_id: int,
            status: str,
            answer: str | None = None,
            intent: str | None = None,
            retrieval_documents: list | None = None,
            error_type: str | None = None,
            error_message: str | None = None,
            latency_ms: int | None = None,
            token_usage: int | None = None,
            prompt_version: str | None = None,
            intent_confidence: float | None = None,
            tools_called: list | None = None,
            confirmed: bool | None = None
    ) -> AgentLog | None:

        """
        更新日志为终态（success / failed / denied）
        """

        log = db.get(
            AgentLog,
            log_id
        )

        if not log:
            return None

        log.status = status

        if answer is not None:
            log.answer = answer

        if intent is not None:
            log.intent = intent

        if retrieval_documents is not None:
            log.retrieval_documents = retrieval_documents

        if error_type is not None:
            log.error_type = error_type

        if error_message is not None:
            log.error_message = error_message

        if latency_ms is not None:
            log.latency_ms = int(latency_ms)

            # 兼容旧字段
            log.cost_time = latency_ms / 1000.0

        if token_usage is not None:
            log.token_usage = token_usage

            # 兼容旧字段
            log.tokens = token_usage

        if prompt_version is not None:
            log.prompt_version = prompt_version

        if intent_confidence is not None:
            log.intent_confidence = intent_confidence

        if tools_called is not None:
            log.tools_called = tools_called

        if confirmed is not None:
            log.confirmed = confirmed

        db.add(log)

        db.commit()

        return log


    def list(
            self,
            db: Session,
            *,
            tenant_id: str,
            user_id: int | None = None,
            channel: str | None = None,
            status: str | None = None,
            start_time: datetime | None = None,
            end_time: datetime | None = None,
            offset: int = 0,
            limit: int = 20,
            include_archived: bool = False
    ):

        """
        按租户隔离查询日志

        默认排除已归档日志
        """

        query = db.query(AgentLog)

        if tenant_id is not None:
            query = query.filter(
                AgentLog.tenant_id == tenant_id
            )

        if not include_archived:
            query = query.filter(
                AgentLog.archived_at.is_(None)
            )

        query = self._apply_filters(
            query,
            user_id=user_id,
            channel=channel,
            status=status,
            start_time=start_time,
            end_time=end_time,
        )

        return (
            query
            .order_by(AgentLog.id.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )


    def count(
            self,
            db: Session,
            *,
            tenant_id: str,
            user_id: int | None = None,
            channel: str | None = None,
            status: str | None = None,
            start_time: datetime | None = None,
            end_time: datetime | None = None,
            include_archived: bool = False
    ) -> int:

        query = db.query(func.count(AgentLog.id))

        if tenant_id is not None:
            query = query.filter(
                AgentLog.tenant_id == tenant_id
            )

        if not include_archived:
            query = query.filter(
                AgentLog.archived_at.is_(None)
            )

        query = self._apply_filters(
            query,
            user_id=user_id,
            channel=channel,
            status=status,
            start_time=start_time,
            end_time=end_time,
        )

        return int(query.scalar() or 0)


    def archive_expired(
            self,
            db: Session,
            tenant_id: str,
            before: datetime
    ) -> int:

        """
        将指定租户在 before 之前的日志标记为已归档

        只标记不删除（保留审计追踪）
        """

        now = datetime.now()

        filters = [
            AgentLog.archived_at.is_(None),
            AgentLog.created_at < before,
        ]

        if tenant_id is not None:
            filters.append(
                AgentLog.tenant_id == tenant_id
            )

        result = (
            db.query(AgentLog)
            .filter(*filters)
            .update(
                {"archived_at": now},
                synchronize_session=False,
            )
        )

        db.commit()

        return int(result or 0)


    def statistics(
            self,
            db: Session,
            tenant_id: str,
            today_start: datetime
    ) -> dict:

        """
        审计统计（租户隔离）
        """

        base = db.query(AgentLog)

        if tenant_id is not None:
            base = base.filter(
                AgentLog.tenant_id == tenant_id
            )

        total = (
            base
            .filter(AgentLog.archived_at.is_(None))
            .count()
        )

        today = (
            base
            .filter(
                AgentLog.archived_at.is_(None),
                AgentLog.created_at >= today_start,
            )
            .count()
        )

        archived = (
            base
            .filter(AgentLog.archived_at.is_not(None))
            .count()
        )

        # 存储占用估算：question + answer 的 UTF-8 字节数
        rows = (
            base
            .with_entities(
                func.coalesce(func.length(AgentLog.question), 0),
                func.coalesce(func.length(AgentLog.answer), 0),
            )
            .all()
        )

        # func.length 返回字符数，估算字节：中文按 3 字节
        storage_bytes = sum(
            (q + a) * 3
            for q, a in rows
        )

        return {
            "total": total,
            "today": today,
            "archived": archived,
            "storage_size": int(storage_bytes),
        }


    def today_stats(
            self,
            db: Session,
            tenant_id: str,
            today_start: datetime
    ) -> dict:

        """
        今日问答统计（租户隔离）
        """

        base = db.query(AgentLog)

        if tenant_id is not None:
            base = base.filter(
                AgentLog.tenant_id == tenant_id
            )

        base = base.filter(
            AgentLog.created_at >= today_start
        )

        finished = [
            AgentLog.status.in_(
                ("success", "failed", "denied")
            )
        ]

        total_today = base.count()

        success_today = (
            base
            .filter(AgentLog.status == "success")
            .count()
        )

        avg_latency = (
            base
            .filter(*finished)
            .with_entities(func.avg(AgentLog.latency_ms))
            .scalar()
        )

        avg_tokens = (
            base
            .with_entities(func.avg(AgentLog.token_usage))
            .scalar()
        )

        tokens_today = (
            base
            .with_entities(func.coalesce(func.sum(AgentLog.token_usage), 0))
            .scalar()
        )

        total_finished = (
            base
            .filter(*finished)
            .count()
        )

        success_rate = (
            round(
                success_today / total_finished,
                4
            )
            if total_finished > 0
            else 0.0
        )

        return {
            "today_count": total_today,
            "success_rate": success_rate,
            "avg_latency_ms": round(
                float(avg_latency or 0),
                1
            ),
            "avg_tokens": round(
                float(avg_tokens or 0),
                1
            ),
            "tokens_today": int(tokens_today or 0),
        }


    def security_counts(
            self,
            db: Session,
            tenant_id: str
    ) -> dict:

        """
        安全统计：拒绝 / 失败（租户隔离）
        """

        denied = db.query(AgentLog).filter(
            AgentLog.status == "denied"
        )

        failed = db.query(AgentLog).filter(
            AgentLog.status == "failed"
        )

        if tenant_id is not None:
            denied = denied.filter(
                AgentLog.tenant_id == tenant_id
            )
            failed = failed.filter(
                AgentLog.tenant_id == tenant_id
            )

        return {
            "denied_count": denied.count(),
            "failed_count": failed.count(),
        }


    @staticmethod
    def _apply_filters(
            query,
            *,
            user_id,
            channel,
            status,
            start_time,
            end_time
    ):

        if user_id is not None:
            query = query.filter(
                AgentLog.user_id == user_id
            )

        if channel:
            query = query.filter(
                AgentLog.channel == channel
            )

        if status:
            query = query.filter(
                AgentLog.status == status
            )

        if start_time is not None:
            query = query.filter(
                AgentLog.created_at >= start_time
            )

        if end_time is not None:
            query = query.filter(
                AgentLog.created_at <= end_time
            )

        return query
