from sqlalchemy.orm import Session

from work_agent.db.models import AgentTrace, TraceSpan


class TraceRepository:

    """
    链路追踪数据访问
    """

    def create_trace(
            self,
            db: Session,
            *,
            request_id: str,
            tenant_id: str,
            user_id: int | None,
            channel: str,
            status: str,
            total_duration_ms: int,
            span_count: int
    ) -> AgentTrace:

        trace = AgentTrace(
            request_id=request_id,
            tenant_id=tenant_id,
            user_id=user_id,
            channel=channel,
            status=status,
            total_duration_ms=int(total_duration_ms),
            span_count=span_count,
        )

        db.add(trace)

        db.flush()

        return trace


    def bulk_create_spans(
            self,
            db: Session,
            *,
            trace_id: int,
            tenant_id: str,
            spans: list[dict]
    ) -> int:

        """
        批量写入 spans（单事务）
        """

        for span in spans:

            db.add(
                TraceSpan(
                    trace_id=trace_id,
                    tenant_id=tenant_id,
                    span_id=span.get("span_id", ""),
                    parent_span_id=span.get("parent_span_id"),
                    name=span.get("name", ""),
                    component=span.get("component", ""),
                    duration_ms=int(
                        span.get("duration_ms", 0)
                    ),
                    status=span.get("status", "ok"),
                    error_type=span.get("error_type"),
                    error_message=span.get("error_message"),
                    attributes=span.get("attributes"),
                )
            )

        return len(spans)


    def list_by_tenant(
            self,
            db: Session,
            *,
            tenant_id: str,
            status: str | None = None,
            channel: str | None = None,
            offset: int = 0,
            limit: int = 20
    ) -> list[AgentTrace]:

        query = (
            db.query(AgentTrace)
            .filter(AgentTrace.tenant_id == tenant_id)
        )

        if status:
            query = query.filter(
                AgentTrace.status == status
            )

        if channel:
            query = query.filter(
                AgentTrace.channel == channel
            )

        return (
            query
            .order_by(AgentTrace.id.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )


    def count_by_tenant(
            self,
            db: Session,
            *,
            tenant_id: str,
            status: str | None = None,
            channel: str | None = None
    ) -> int:

        query = (
            db.query(AgentTrace)
            .filter(AgentTrace.tenant_id == tenant_id)
        )

        if status:
            query = query.filter(
                AgentTrace.status == status
            )

        if channel:
            query = query.filter(
                AgentTrace.channel == channel
            )

        return int(query.count())


    def get_by_request_id(
            self,
            db: Session,
            request_id: str
    ) -> AgentTrace | None:

        return (
            db.query(AgentTrace)
            .filter(AgentTrace.request_id == request_id)
            .first()
        )


    def get_spans_by_trace(
            self,
            db: Session,
            trace_id: int
    ) -> list[TraceSpan]:

        return (
            db.query(TraceSpan)
            .filter(TraceSpan.trace_id == trace_id)
            .order_by(TraceSpan.id)
            .all()
        )
