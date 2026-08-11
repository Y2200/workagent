"""
管理驾驶舱统计测试

验证：
- 数据准确（文档/问答/安全统计与真实数据一致）
- 租户隔离（企业A统计不含企业B数据）

用法：
    python -m work_agent.scripts.test_dashboard
"""

import time

from uuid import uuid4

from fastapi.testclient import TestClient

from work_agent.core.audit_logger import audit_logger
from work_agent.core.container import dashboard_service, document_service
from work_agent.db.models import AgentLog
from work_agent.db.session import SessionLocal
from work_agent.main import app
from work_agent.repositories.document_repository import DocumentRepository
from work_agent.repositories.tenant_repository import TenantRepository
from work_agent.scripts.seed_tenants import seed_tenants


def _tenant_id_by_corp(corp_id: str) -> str:

    db = SessionLocal()

    try:

        return str(
            TenantRepository().get_by_corp_id(
                db,
                corp_id
            ).id
        )

    finally:

        db.close()


def _wait_ready(
        document_id: int,
        timeout: float = 60.0
):

    repository = DocumentRepository()

    db = SessionLocal()

    try:

        start = time.time()

        while time.time() - start < timeout:

            db.expire_all()

            document = repository.get_by_id(
                db,
                document_id
            )

            if document and document.status in (
                    "ready",
                    "failed"
            ):
                return document.status

            time.sleep(1)

        return "timeout"

    finally:

        db.close()


def _make_log(
        tenant_id: str,
        *,
        status: str = "success",
        question: str = "测试问题",
        answer: str = "测试回答"
) -> str:

    """
    通过真实审计路径产生日志，返回 request_id
    """

    request_id = str(uuid4())

    ctx = audit_logger.log_request(
        request_id=request_id,
        tenant_id=tenant_id,
        user_id=None,
        channel="wechat",
        question=question,
    )

    if status == "success":
        audit_logger.log_success(
            ctx,
            answer=answer,
            status="success",
            latency_ms=1000,
            token_usage=500,
        )

    elif status == "denied":
        audit_logger.log_success(
            ctx,
            answer=answer,
            status="denied",
            latency_ms=1000,
        )

    else:
        audit_logger.log_error(
            ctx,
            error_type="ValueError",
            error_message="test error",
            status="failed",
        )

    return request_id


def _delete_logs(request_ids: list[str]):

    db = SessionLocal()

    try:

        db.query(AgentLog).filter(
            AgentLog.request_id.in_(request_ids)
        ).delete(
            synchronize_session=False
        )

        db.commit()

    finally:

        db.close()


def test():

    seed_tenants()

    tenant_a_id = _tenant_id_by_corp("ww_corp_A")

    tenant_b_id = _tenant_id_by_corp("ww_corp_B")

    # 基线
    before_a = dashboard_service.get_stats(tenant_a_id)

    before_b = dashboard_service.get_stats(tenant_b_id)

    # ======================
    # 准备数据：企业A 1文档 + 2日志(1成功1拒绝)；企业B 1日志(成功)
    # ======================

    doc_a = document_service.upload(
        filename="dashboard_test.md",
        data="dashboard 测试文档内容".encode("utf-8"),
        category="测试",
        uploader="admin_A",
        tenant_id=tenant_a_id,
        visibility="public",
    )

    _wait_ready(doc_a.id)

    request_ids = [
        _make_log(tenant_a_id, status="success", question="企业A问题1"),
        _make_log(tenant_a_id, status="denied", question="企业A问题2"),
        _make_log(tenant_b_id, status="success", question="企业B问题"),
    ]

    # ======================
    # 验证：数据准确
    # ======================

    after_a = dashboard_service.get_stats(tenant_a_id)

    assert after_a["documents"]["total"] == before_a["documents"]["total"] + 1, after_a["documents"]

    assert after_a["documents"]["ready"] == before_a["documents"]["ready"] + 1, after_a["documents"]

    assert after_a["qa"]["today_count"] == before_a["qa"]["today_count"] + 2, after_a["qa"]

    assert after_a["security"]["denied_count"] == before_a["security"]["denied_count"] + 1, after_a["security"]

    assert 0.0 <= after_a["qa"]["success_rate"] <= 1.0, after_a["qa"]["success_rate"]

    assert after_a["tenant"]["total"] == 2, after_a["tenant"]

    assert after_a["usage"]["estimated_cost"] >= 0, after_a["usage"]

    print(
        f"场景1 ✅ 企业A统计准确: "
        f"documents={after_a['documents']}, "
        f"qa.today={after_a['qa']['today_count']}, "
        f"denied={after_a['security']['denied_count']}, "
        f"cost=¥{after_a['usage']['estimated_cost']}"
    )

    # ======================
    # 验证：租户隔离
    # ======================

    after_b = dashboard_service.get_stats(tenant_b_id)

    # 企业B没有新增文档，文档数应与基线一致
    assert after_b["documents"]["total"] == before_b["documents"]["total"], after_b["documents"]

    # 企业B今日问答只增加1条（自己的），不含企业A的2条
    assert after_b["qa"]["today_count"] == before_b["qa"]["today_count"] + 1, after_b["qa"]

    assert after_b["security"]["denied_count"] == before_b["security"]["denied_count"], after_b["security"]

    print(
        f"场景2 ✅ 企业B统计隔离: documents={after_b['documents']['total']} "
        f"(不含A), qa.today={after_b['qa']['today_count']} (仅自己的1条)"
    )

    # ======================
    # HTTP 层验证：admin_A 登录查 dashboard/stats
    # ======================

    client = TestClient(app)

    resp = client.post(
        "/api/admin/auth/login",
        json={
            "username": "admin_A",
            "password": "test123"
        }
    )

    assert resp.status_code == 200, resp.text

    headers_a = {
        "Authorization": f"Bearer {resp.json()['access_token']}"
    }

    resp = client.get(
        "/api/admin/dashboard/stats",
        headers=headers_a,
    )

    assert resp.status_code == 200, resp.text

    http_stats = resp.json()

    assert http_stats["documents"]["total"] == after_a["documents"]["total"], http_stats

    assert http_stats["tenant"]["total"] == 2, http_stats

    print(
        f"场景3 ✅ HTTP层 dashboard/stats 正常: "
        f"documents={http_stats['documents']['total']}, "
        f"qa.today={http_stats['qa']['today_count']}"
    )

    # ======================
    # 清理
    # ======================

    document_service.delete(
        doc_a.id,
        tenant_id=tenant_a_id,
    )

    _delete_logs(request_ids)

    print("Dashboard 统计测试全部通过")


if __name__ == "__main__":

    test()
