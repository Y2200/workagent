"""
Agent Health Monitoring 测试（P5-5-6）

覆盖：
- 就绪探针（关键依赖 PG/Milvus/MinIO）
- 组件健康检查
- 运行时指标随执行递增
- admin 端点权限（非 system:manage → 403）
- 公共就绪端点可访问

用法：
    python -m work_agent.scripts.test_health_monitoring
"""

from work_agent.core.container import (
    cost_governance_service,
    document_service,
)
from work_agent.core.health_metrics import health_metrics
from work_agent.db.models import AgentConfig
from work_agent.db.session import SessionLocal
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


def _cleanup_budget():

    db = SessionLocal()

    try:

        db.query(AgentConfig).filter(
            AgentConfig.config_key == "cost.monthly_budget"
        ).delete(synchronize_session=False)

        db.commit()

    finally:

        db.close()

    cost_governance_service._get_config_service()._cache.clear()


def test():

    seed_tenants()

    _cleanup_budget()

    tenant_a = _tenant_id("ww_corp_A")

    # ======================
    # 场景1：就绪探针
    # ======================

    from fastapi.testclient import TestClient

    from work_agent.main import app

    client = TestClient(app)

    ready = client.get("/health/ready")

    assert ready.status_code == 200, ready.text

    body = ready.json()

    assert body["ready"] is True, body

    status_map = {
        item["name"]: item["status"]
        for item in body["components"]
    }

    assert status_map["postgres"] == "ok", status_map

    assert status_map["milvus"] == "ok", status_map

    assert status_map["minio"] == "ok", status_map

    print(f"场景1 ✅ 就绪探针（ready={body['ready']}，关键依赖全 ok）")

    # ======================
    # 场景2：组件健康检查（admin）
    # ======================

    login = client.post(
        "/api/admin/auth/login",
        json={"username": "admin_A", "password": "test123"},
    )

    headers = {
        "Authorization": f"Bearer {login.json()['access_token']}"
    }

    comps = client.get(
        "/api/admin/health/components",
        headers=headers,
    )

    assert comps.status_code == 200, comps.text

    comp_map = {
        item["name"]: item["status"]
        for item in comps.json()["components"]
    }

    for name in ("postgres", "milvus", "minio", "config_center", "prompt"):
        assert comp_map[name] == "ok", (name, comp_map)

    assert comp_map["redis"] in ("ok", "warn"), comp_map

    print(f"场景2 ✅ 组件健康检查（{sorted(comp_map)}）")

    # ======================
    # 场景3：运行时指标随执行递增（确定性：预算拦截路径）
    # ======================

    before = health_metrics.snapshot()

    # 预算置 0 → runtime 预算拦截（不调 LLM），denied + requests 递增
    cost_governance_service.set_budget(
        tenant_id=tenant_a,
        budget=0.0,
        updated_by="admin_A",
    )

    from work_agent.agent.runtime import agent_runtime

    user = _user("A财务员工")

    result = agent_runtime.execute(
        message="财务报销制度是什么",
        user=user,
        channel="test",
    )

    assert "预算已用完" in result["response"], result["response"]

    after = health_metrics.snapshot()

    assert after["requests"] == before["requests"] + 1, (before, after)

    assert after["denied"] == before["denied"] + 1, (before, after)

    assert after["avg_latency_ms"] >= 0, after

    print("场景3 ✅ 运行时指标随执行递增（requests/denied +1）")

    # ======================
    # 场景4：admin 端点权限（非 system:manage → 403）
    # ======================

    login_user = client.post(
        "/api/admin/auth/login",
        json={"username": "员工A", "password": "test123"},
    )

    user_headers = {
        "Authorization": f"Bearer {login_user.json()['access_token']}"
    }

    denied = client.get(
        "/api/admin/health/metrics",
        headers=user_headers,
    )

    assert denied.status_code == 403, denied.text

    # 管理员可读
    metrics = client.get(
        "/api/admin/health/metrics",
        headers=headers,
    )

    assert metrics.status_code == 200, metrics.text

    assert "requests" in metrics.json(), metrics.json()

    print("场景4 ✅ admin 端点权限（USER 403 / 管理员 200）")

    # ======================
    # 场景5：健康/存活与指标端点
    # ======================

    liveness = client.get("/health")

    assert liveness.status_code == 200, liveness.text

    resilience = client.get(
        "/api/admin/health/resilience",
        headers=headers,
    )

    assert resilience.status_code == 200, resilience.text

    print("场景5 ✅ 存活 + 熔断状态端点")

    # ======================
    # 清理
    # ======================

    _cleanup_budget()

    print("Agent Health Monitoring 测试全部通过")


if __name__ == "__main__":

    test()
