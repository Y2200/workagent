"""
审计日志生命周期测试

验证：
- 归档过期日志（标记 archived_at）
- 归档后默认列表不展示、统计正确
- HTTP 层 statistics/archive 端点
- 租户隔离

用法：
    python -m work_agent.scripts.test_audit_lifecycle
"""

from datetime import datetime, timedelta

from uuid import uuid4

from fastapi.testclient import TestClient

from work_agent.core.audit_logger import audit_logger
from work_agent.core.container import audit_service
from work_agent.db.models import AgentLog
from work_agent.db.session import SessionLocal
from work_agent.main import app
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


def _make_log(
        tenant_id: str,
        *,
        days_old: int = 0
) -> str:

    request_id = str(uuid4())

    ctx = audit_logger.log_request(
        request_id=request_id,
        tenant_id=tenant_id,
        user_id=None,
        channel="wechat",
        question="生命周期测试问题",
    )

    audit_logger.log_success(
        ctx,
        answer="测试回答",
        status="success",
        latency_ms=100,
        token_usage=100,
    )

    # 回填 created_at 模拟历史日志
    if days_old > 0:

        old = datetime.now() - timedelta(days=days_old)

        db = SessionLocal()

        try:

            db.query(AgentLog).filter(
                AgentLog.request_id == request_id
            ).update(
                {"created_at": old},
                synchronize_session=False,
            )

            db.commit()

        finally:

            db.close()

    return request_id


def test():

    seed_tenants()

    tenant_a_id = _tenant_id_by_corp("ww_corp_A")

    tenant_b_id = _tenant_id_by_corp("ww_corp_B")

    # 企业A：1条今天 + 1条200天前（过期）；企业B：1条200天前（过期）
    new_id = _make_log(tenant_a_id, days_old=0)

    old_a_id = _make_log(tenant_a_id, days_old=200)

    old_b_id = _make_log(tenant_b_id, days_old=200)

    # ======================
    # 归档前：统计
    # ======================

    stats_before = audit_service.get_statistics(tenant_a_id)

    # 默认列表不含已归档（此时无归档）
    db = SessionLocal()

    try:

        active_before = (
            db.query(AgentLog)
            .filter(
                AgentLog.tenant_id == tenant_a_id,
                AgentLog.archived_at.is_(None),
            )
            .count()
        )

    finally:

        db.close()

    assert stats_before["archived"] >= 0

    # ======================
    # HTTP 归档端点（企业A）
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

    resp = client.post(
        "/api/admin/audit/archive",
        headers=headers_a,
    )

    assert resp.status_code == 200, resp.text

    archived_count = resp.json()["archived_count"]

    assert archived_count >= 1, f"企业A应至少归档1条过期日志, got {archived_count}"

    print(f"场景1 ✅ 归档: 企业A归档 {archived_count} 条过期日志")

    # ======================
    # 归档后：旧日志被标记、默认列表不展示
    # ======================

    db = SessionLocal()

    try:

        old_a = db.query(AgentLog).filter(
            AgentLog.request_id == old_a_id
        ).first()

        assert old_a.archived_at is not None, "过期日志应被标记归档"

        # 新日志不应被归档
        new_a = db.query(AgentLog).filter(
            AgentLog.request_id == new_id
        ).first()

        assert new_a.archived_at is None, "新日志不应被归档"

        active_after = (
            db.query(AgentLog)
            .filter(
                AgentLog.tenant_id == tenant_a_id,
                AgentLog.archived_at.is_(None),
            )
            .count()
        )

    finally:

        db.close()

    assert active_after == active_before - 1, "归档后活跃日志应减1"

    # 默认列表（服务层）不含已归档
    page = audit_service.list_logs(
        tenant_id=tenant_a_id,
        page_size=50,
    )

    request_ids_visible = {
        item.request_id
        for item in page["items"]
    }

    assert old_a_id not in request_ids_visible, "默认列表不应含已归档日志"

    assert new_id in request_ids_visible, "新日志应在列表中"

    print(
        f"场景2 ✅ 归档后: 旧日志已标记, 默认列表不含归档(活跃{active_after})"
    )

    # ======================
    # 租户隔离：企业B过期日志不受企业A归档影响
    # ======================

    db = SessionLocal()

    try:

        old_b = db.query(AgentLog).filter(
            AgentLog.request_id == old_b_id
        ).first()

    finally:

        db.close()

    assert old_b.archived_at is None, "企业A归档不应影响企业B日志"

    print("场景3 ✅ 租户隔离: 企业A归档不影响企业B")

    # ======================
    # statistics 端点
    # ======================

    resp = client.get(
        "/api/admin/audit/statistics",
        headers=headers_a,
    )

    assert resp.status_code == 200, resp.text

    http_stats = resp.json()

    assert http_stats["archived"] >= 1, http_stats

    assert http_stats["storage_size"] > 0, http_stats

    print(
        f"场景4 ✅ statistics 端点: total={http_stats['total']}, "
        f"today={http_stats['today']}, archived={http_stats['archived']}, "
        f"storage={http_stats['storage_size']}B"
    )

    # ======================
    # 清理测试日志
    # ======================

    db = SessionLocal()

    try:

        db.query(AgentLog).filter(
            AgentLog.request_id.in_([new_id, old_a_id, old_b_id])
        ).delete(
            synchronize_session=False
        )

        db.commit()

    finally:

        db.close()

    print("审计生命周期测试全部通过")


if __name__ == "__main__":

    test()
