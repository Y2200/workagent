"""
Agent Trace 测试（P5-5-1）

覆盖：
- 正常执行产生 trace + 各阶段 span
- 追踪详情/瀑布结构
- 跨租户隔离
- 异常路径 span 记 error
- 无活跃 trace 时为空操作

用法：
    python -m work_agent.scripts.test_agent_trace
"""

import time

from work_agent.core.container import document_service, trace_service
from work_agent.core.trace import tracer
from work_agent.db.models import AgentTrace
from work_agent.db.session import SessionLocal
from work_agent.repositories.document_repository import DocumentRepository
from work_agent.repositories.tenant_repository import TenantRepository
from work_agent.repositories.user_repository import UserRepository
from work_agent.scripts.seed_tenants import seed_tenants


def _tenant_id(corp_id: str) -> str:

    db = SessionLocal()

    try:

        return str(
            TenantRepository().get_by_corp_id(db, corp_id).id
        )

    finally:

        db.close()


def _user(username: str):

    db = SessionLocal()

    try:

        return UserRepository().get_by_username(
            db,
            username
        )

    finally:

        db.close()


def _wait_ready(document_id: int, timeout: float = 90.0):

    db = SessionLocal()

    try:

        start = time.time()

        while time.time() - start < timeout:

            db.expire_all()

            doc = DocumentRepository().get_by_id(
                db,
                document_id
            )

            if doc and doc.status in ("ready", "failed"):
                return doc.status

            time.sleep(1)

        return "timeout"

    finally:

        db.close()


def _trace_count(tenant_id: str) -> int:

    db = SessionLocal()

    try:

        return (
            db.query(AgentTrace)
            .filter(AgentTrace.tenant_id == tenant_id)
            .count()
        )

    finally:

        db.close()


def _cleanup():

    from work_agent.scripts.test_utils import cleanup_tenant_data

    from work_agent.db.models import AgentTrace, TraceSpan

    cleanup_tenant_data()

    # 清理本次测试的追踪记录
    db = SessionLocal()

    try:

        trace_ids = [
            row[0]
            for row in db.query(AgentTrace.id).filter(
                AgentTrace.tenant_id.in_(["1", "2"])
            ).all()
        ]

        if trace_ids:

            db.query(TraceSpan).filter(
                TraceSpan.trace_id.in_(trace_ids)
            ).delete(synchronize_session=False)

        db.query(AgentTrace).filter(
            AgentTrace.tenant_id.in_(["1", "2"])
        ).delete(synchronize_session=False)

        db.commit()

    finally:

        db.close()


def test():

    seed_tenants()

    _cleanup()

    # 用租户 A 用户执行（员工A 为默认单租户 ""，不适用租户隔离断言）
    user = _user("A财务员工")

    tenant_a = user.tenant_id

    tenant_b = _tenant_id("ww_corp_B")

    assert tenant_a, "A财务员工应属于租户 A"

    # ======================
    # 准备：租户A知识文档
    # ======================

    doc = document_service.upload(
        filename="财务报销制度.md",
        data=(
            "财务报销制度：差旅报销需提交发票，"
            "超标需审批。"
        ).encode("utf-8"),
        category="财务管理",
        uploader="admin_A",
        tenant_id=tenant_a,
    )

    assert _wait_ready(doc.id) == "ready", doc.id

    # ======================
    # 场景1：正常执行产生 trace + spans
    # ======================

    from work_agent.agent.runtime import agent_runtime

    result = agent_runtime.execute(
        message="财务报销制度是什么",
        user=user,
        channel="wechat",
    )

    request_id = result["request_id"]

    assert request_id, result

    detail = trace_service.get_trace(
        request_id=request_id,
        tenant_id=tenant_a,
    )

    assert detail is not None, "追踪应存在"

    trace = detail["trace"]

    assert trace.status == "ok", trace.status

    assert trace.total_duration_ms > 0, trace.total_duration_ms

    spans = detail["spans"]

    span_names = {span.name for span in spans}

    # 核心阶段 span 齐全
    assert {
        "context_builder",
        "intent_router",
        "planner",
        "supervisor",
        "audit",
    } <= span_names, span_names

    # 全部 span ok 且耗时非负
    for span in spans:
        assert span.status == "ok", (span.name, span.status)
        assert span.duration_ms >= 0, span.name

    # 瀑布非空
    assert detail["waterfall"], detail["waterfall"]

    print(
        f"场景1 ✅ 正常执行（trace={trace.status}, "
        f"spans={sorted(span_names)}, duration={trace.total_duration_ms}ms, "
        f"waterfall_depth={len(detail['waterfall'])}）"
    )

    # ======================
    # 场景2：跨租户隔离
    # ======================

    cross = trace_service.get_trace(
        request_id=request_id,
        tenant_id=tenant_b,
    )

    assert cross is None, "B 租户不应看到 A 的追踪"

    print("场景2 ✅ 跨租户隔离（B 不可见 A 的 trace）")

    # ======================
    # 场景3：异常路径 span 记 error
    # ======================

    before = _trace_count(tenant_a)

    tracer.start(
        request_id="trace-error-test",
        tenant_id=tenant_a,
        user_id=user.id,
        channel="test",
    )

    try:

        with tracer.span("explode", component="test"):

            raise ValueError("boom")

    except ValueError:
        pass

    tracer.finish(
        status="error",
        error_type="ValueError",
        error_message="boom",
    )

    error_detail = trace_service.get_trace(
        request_id="trace-error-test",
        tenant_id=tenant_a,
    )

    assert error_detail is not None

    assert error_detail["trace"].status == "error", error_detail["trace"].status

    error_spans = error_detail["spans"]

    assert len(error_spans) == 1, error_spans

    assert error_spans[0].status == "error", error_spans[0].status

    assert error_spans[0].error_type == "ValueError", error_spans[0].error_type

    assert _trace_count(tenant_a) == before + 1, "应新增一条 trace"

    print("场景3 ✅ 异常路径（span 记 error + trace status=error）")

    # ======================
    # 场景4：无活跃 trace 时空操作
    # ======================

    before = _trace_count(tenant_a)

    with tracer.span("orphan", component="test"):
        pass

    tracer.finish()

    assert _trace_count(tenant_a) == before, "无活跃 trace 不应写库"

    print("场景4 ✅ 无活跃 trace 空操作（不写库）")

    # ======================
    # 场景5：HTTP API（租户隔离 + 详情）
    # ======================

    from fastapi.testclient import TestClient

    from work_agent.main import app

    client = TestClient(app)

    login = client.post(
        "/api/admin/auth/login",
        json={"username": "admin_A", "password": "test123"},
    )

    token = login.json()["access_token"]

    headers = {"Authorization": f"Bearer {token}"}

    listing = client.get(
        "/api/admin/traces",
        headers=headers,
    )

    assert listing.status_code == 200, listing.text

    body = listing.json()

    assert body["total"] >= 1, body

    request_ids = {item["request_id"] for item in body["items"]}

    assert request_id in request_ids, request_ids

    detail_resp = client.get(
        f"/api/admin/traces/{request_id}",
        headers=headers,
    )

    assert detail_resp.status_code == 200, detail_resp.text

    assert detail_resp.json()["waterfall"], detail_resp.json()

    # B 管理员访问 A 的 trace → 404
    login_b = client.post(
        "/api/admin/auth/login",
        json={"username": "admin_B", "password": "test123"},
    )

    headers_b = {
        "Authorization": f"Bearer {login_b.json()['access_token']}"
    }

    cross_resp = client.get(
        f"/api/admin/traces/{request_id}",
        headers=headers_b,
    )

    assert cross_resp.status_code == 404, cross_resp.text

    print("场景5 ✅ HTTP API（列表 + 详情 + 跨租户 404）")

    # ======================
    # 清理
    # ======================

    document_service.delete(doc.id, tenant_id=tenant_a)

    _cleanup()

    print("Agent Trace 测试全部通过")


if __name__ == "__main__":

    test()
