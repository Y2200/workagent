from work_agent.db.session import SessionLocal
from work_agent.repositories.trace_repository import TraceRepository


class TraceService:

    """
    链路追踪查询服务（租户隔离）
    """

    def __init__(
            self,
            repository: TraceRepository | None = None
    ):

        self.repository = repository or TraceRepository()


    def list_traces(
            self,
            *,
            tenant_id: str,
            status: str | None = None,
            channel: str | None = None,
            page: int = 1,
            page_size: int = 20
    ) -> dict:

        """
        追踪列表（租户隔离分页）
        """

        offset = (page - 1) * page_size

        db = SessionLocal()

        try:

            items = self.repository.list_by_tenant(
                db,
                tenant_id=tenant_id,
                status=status,
                channel=channel,
                offset=offset,
                limit=page_size,
            )

            total = self.repository.count_by_tenant(
                db,
                tenant_id=tenant_id,
                status=status,
                channel=channel,
            )

            return {
                "items": items,
                "total": total,
                "page": page,
                "page_size": page_size,
            }

        finally:

            db.close()


    def get_trace(
            self,
            *,
            request_id: str,
            tenant_id: str
    ) -> dict | None:

        """
        追踪详情（含 spans 瀑布），跨租户返回 None
        """

        db = SessionLocal()

        try:

            trace = self.repository.get_by_request_id(
                db,
                request_id
            )

            if not trace:
                return None

            # 租户隔离：不能查看其他租户的追踪
            if trace.tenant_id != tenant_id:
                return None

            spans = self.repository.get_spans_by_trace(
                db,
                trace.id
            )

            return {
                "trace": trace,
                "spans": spans,
                "waterfall": _build_waterfall(spans),
            }

        finally:

            db.close()


def _build_waterfall(
        spans
) -> list[dict]:

    """
    将扁平 spans 组装成瀑布树（按 parent 嵌套）
    """

    by_id = {}

    for span in spans:

        by_id[span.span_id] = {
            "span_id": span.span_id,
            "name": span.name,
            "component": span.component,
            "duration_ms": span.duration_ms,
            "status": span.status,
            "attributes": span.attributes,
            "children": [],
        }

    roots = []

    for span in spans:

        node = by_id[span.span_id]

        if span.parent_span_id and span.parent_span_id in by_id:

            by_id[span.parent_span_id]["children"].append(node)

        else:

            roots.append(node)

    return roots
