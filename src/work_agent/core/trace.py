"""
请求链路追踪（Agent Trace）

TraceManager：
- start()  开启一次 trace（contextvar 持有）
- span()   记录一个阶段片段（支持嵌套，parent 自动关联）
- finish() 收尾并单事务批量写库

设计要点：
- span 先内存缓冲，finish 时一次事务写入（trace + 全部 spans），避免 N+1 写
- 追踪为纯增量能力：无活跃 trace 时 span() 为空操作；写库失败静默不抛
- 业务代码不依赖追踪结果，追踪失败绝不破坏主链路
"""

import time

from contextvars import ContextVar
from uuid import uuid4

from work_agent.db.session import SessionLocal
from work_agent.repositories.trace_repository import TraceRepository


# 当前活跃 trace（None = 未启用追踪）
_current_trace: ContextVar[object | None] = ContextVar(
    "agent_trace",
    default=None,
)

# 当前 span 栈（用于父级关联）
_span_stack: ContextVar[list] = ContextVar(
    "agent_trace_span_stack",
    default=[],
)


class TraceSpan:

    """
    内存中的 span 记录（尚未落库）
    """

    __slots__ = (
        "span_id",
        "parent_span_id",
        "name",
        "component",
        "started",
        "duration_ms",
        "status",
        "error_type",
        "error_message",
        "attributes",
    )

    def __init__(
            self,
            *,
            name: str,
            component: str,
            parent_span_id: str | None
    ):

        self.span_id = str(uuid4())

        self.parent_span_id = parent_span_id

        self.name = name

        self.component = component

        self.started = time.perf_counter()

        self.duration_ms = 0

        self.status = "ok"

        self.error_type = None

        self.error_message = None

        self.attributes = {}


class Trace:

    """
    一次请求的追踪容器
    """

    def __init__(
            self,
            *,
            request_id: str,
            tenant_id: str,
            user_id: int | None,
            channel: str
    ):

        self.request_id = request_id

        self.tenant_id = tenant_id

        self.user_id = user_id

        self.channel = channel

        self.status = "ok"

        self.error_type = None

        self.error_message = None

        self.started = time.perf_counter()

        self.total_duration_ms = 0

        self.spans: list[TraceSpan] = []


class TraceManager:

    """
    追踪管理器（contextvar 支持嵌套/并发）
    """

    def __init__(
            self,
            repository: TraceRepository | None = None
    ):

        self.repository = repository or TraceRepository()


    def start(
            self,
            *,
            request_id: str,
            tenant_id: str,
            user_id: int | None = None,
            channel: str = "wechat"
    ) -> Trace | None:

        """
        开启一次追踪，返回 Trace（失败返回 None，不抛异常）
        """

        try:

            trace = Trace(
                request_id=request_id,
                tenant_id=tenant_id,
                user_id=user_id,
                channel=channel,
            )

            _current_trace.set(trace)

            _span_stack.set([])

            return trace

        except Exception:

            return None


    def finish(
            self,
            status: str = "ok",
            error_type: str = "",
            error_message: str = ""
    ) -> None:

        """
        收尾追踪：计算总耗时并单事务写库

        任何写库异常静默忽略（追踪为增量能力）
        """

        trace = _current_trace.get()

        if trace is None:
            return

        try:

            trace.status = status

            trace.error_type = error_type or None

            trace.error_message = error_message or None

            trace.total_duration_ms = int(
                (time.perf_counter() - trace.started) * 1000
            )

            self._flush(trace)

        except Exception:

            pass

        finally:

            try:

                _current_trace.set(None)

                _span_stack.set([])

            except Exception:
                pass


    def span(
            self,
            name: str,
            component: str = "",
            **attributes
    ) -> "TraceSpanContext":

        """
        开启一个阶段 span（上下文管理器）

        无活跃 trace 时为空操作
        """

        return TraceSpanContext(
            manager=self,
            name=name,
            component=component,
            attributes=dict(attributes),
        )


    def add_attributes(
            self,
            **attributes
    ) -> None:

        """
        向当前 span 追加属性（无活跃 trace/span 时忽略）
        """

        try:

            stack = _span_stack.get()

            if stack:
                stack[-1].attributes.update(attributes)

        except Exception:
            pass


    # ======================
    # 内部
    # ======================

    def _begin_span(
            self,
            name: str,
            component: str,
            attributes: dict
    ) -> TraceSpan:

        trace = _current_trace.get()

        stack = _span_stack.get()

        parent = stack[-1] if stack else None

        span = TraceSpan(
            name=name,
            component=component,
            parent_span_id=parent.span_id if parent else None,
        )

        span.attributes.update(attributes)

        trace.spans.append(span)

        stack.append(span)

        _span_stack.set(stack)

        return span


    def _end_span(
            self,
            span: TraceSpan,
            exc: BaseException | None
    ) -> None:

        try:

            span.duration_ms = int(
                (time.perf_counter() - span.started) * 1000
            )

            if exc is not None:

                span.status = "error"

                span.error_type = type(exc).__name__

                span.error_message = str(exc)

            stack = _span_stack.get()

            if stack and stack[-1] is span:
                stack.pop()
                _span_stack.set(stack)

        except Exception:
            pass


    def _flush(self, trace: Trace) -> None:

        """
        单事务写入 trace + spans
        """

        db = SessionLocal()

        try:

            trace_row = self.repository.create_trace(
                db,
                request_id=trace.request_id,
                tenant_id=trace.tenant_id,
                user_id=trace.user_id,
                channel=trace.channel,
                status=trace.status,
                total_duration_ms=trace.total_duration_ms,
                span_count=len(trace.spans),
            )

            self.repository.bulk_create_spans(
                db,
                trace_id=trace_row.id,
                tenant_id=trace.tenant_id,
                spans=[
                    {
                        "span_id": span.span_id,
                        "parent_span_id": span.parent_span_id,
                        "name": span.name,
                        "component": span.component,
                        "duration_ms": span.duration_ms,
                        "status": span.status,
                        "error_type": span.error_type,
                        "error_message": span.error_message,
                        "attributes": span.attributes,
                    }
                    for span in trace.spans
                ],
            )

            db.commit()

        finally:

            db.close()


class TraceSpanContext:

    """
    span 上下文管理器
    """

    def __init__(
            self,
            *,
            manager: TraceManager,
            name: str,
            component: str,
            attributes: dict
    ):

        self.manager = manager

        self.name = name

        self.component = component

        self.attributes = attributes

        self.span: TraceSpan | None = None


    def __enter__(self):

        if _current_trace.get() is None:
            return self

        self.span = self.manager._begin_span(
            self.name,
            self.component,
            self.attributes,
        )

        return self


    def __exit__(self, exc_type, exc_value, tb):

        if self.span is not None:

            exc = exc_value if exc_value else None

            self.manager._end_span(
                self.span,
                exc,
            )

        return False


# 全局单例
tracer = TraceManager()
