"""
LLM Cost Governance 测试（P5-5-4）

覆盖：
- 成本记账 + 用量聚合
- 月度预算 + check_quota
- 预算超限拦截（Runtime 不调 LLM，返回优雅消息 + denied 审计）
- 跨租户隔离
- HTTP API

用法：
    python -m work_agent.scripts.test_llm_cost
"""

from work_agent.core.container import (
    cost_governance_service,
    document_service,
)
from work_agent.db.models import AgentConfig, AgentLog, LLMCostRecord
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


def _cleanup():

    db = SessionLocal()

    try:

        db.query(LLMCostRecord).delete(
            synchronize_session=False
        )

        db.query(AgentConfig).filter(
            AgentConfig.config_key == "cost.monthly_budget"
        ).delete(synchronize_session=False)

        db.commit()

    finally:

        db.close()

    cost_governance_service._get_config_service()._cache.clear()


def _budget_exceeded_logs(tenant_id: str) -> int:

    db = SessionLocal()

    try:

        return (
            db.query(AgentLog)
            .filter(
                AgentLog.tenant_id == tenant_id,
                AgentLog.status == "denied",
                AgentLog.error_type == "budget_exceeded",
            )
            .count()
        )

    finally:

        db.close()


def test():

    seed_tenants()

    _cleanup()

    tenant_a = _tenant_id("ww_corp_A")

    tenant_b = _tenant_id("ww_corp_B")

    # ======================
    # 场景1：成本记账 + 用量聚合
    # ======================

    cost_governance_service.record(
        tenant_id=tenant_a,
        request_id="cost-1",
        user_id=1,
        model="deepseek",
        input_tokens=100,
        output_tokens=200,
    )

    cost_governance_service.record(
        tenant_id=tenant_a,
        request_id="cost-2",
        user_id=1,
        model="deepseek",
        total_tokens=500,
    )

    usage = cost_governance_service.usage(tenant_a)

    assert usage["today"]["requests"] == 2, usage

    assert usage["today"]["tokens"] == 800, usage

    assert usage["today"]["cost"] > 0, usage

    assert usage["month"]["requests"] == 2, usage

    assert len(usage["by_model"]) == 1, usage

    assert usage["by_model"][0]["model"] == "deepseek", usage

    print(
        f"场景1 ✅ 成本记账 + 用量聚合（tokens={usage['today']['tokens']}, "
        f"cost={usage['today']['cost']}）"
    )

    # ======================
    # 场景2：月度预算 + check_quota
    # ======================

    assert cost_governance_service.get_budget(tenant_a) is None

    quota_unlimited = cost_governance_service.check_quota(tenant_a)

    assert quota_unlimited["allowed"] is True, quota_unlimited

    cost_governance_service.set_budget(
        tenant_id=tenant_a,
        budget=10.0,
        updated_by="admin_A",
    )

    quota = cost_governance_service.check_quota(tenant_a)

    assert quota["allowed"] is True, quota

    assert quota["budget"] == 10.0, quota

    assert quota["remaining"] > 0, quota

    print("场景2 ✅ 预算设置 + check_quota")

    # ======================
    # 场景3：预算超限拦截（Runtime 不调 LLM）
    # ======================

    # 清零预算：已花费 > 0 ≥ 预算 0 → 拦截
    cost_governance_service.set_budget(
        tenant_id=tenant_a,
        budget=0.0,
        updated_by="admin_A",
    )

    assert cost_governance_service.check_quota(tenant_a)["allowed"] is False

    from work_agent.agent.runtime import agent_runtime

    user = _user("A财务员工")

    blocked = agent_runtime.execute(
        message="财务报销制度是什么",
        user=user,
        channel="test",
    )

    assert "预算已用完" in blocked["response"], blocked["response"]

    assert blocked["agent"] == "cost_center", blocked["agent"]

    assert blocked.get("tools_called", []) == [], blocked

    # 记录 denied 审计
    assert _budget_exceeded_logs(tenant_a) >= 1

    # 超限请求不计成本
    assert cost_governance_service.usage(tenant_a)["today"]["requests"] == 2

    print("场景3 ✅ 预算超限拦截（不调 LLM + denied 审计）")

    # 恢复预算
    cost_governance_service.set_budget(
        tenant_id=tenant_a,
        budget=None,
        updated_by="admin_A",
    )

    assert cost_governance_service.check_quota(tenant_a)["allowed"] is True

    print("场景3b ✅ 恢复预算")

    # ======================
    # 场景4：跨租户隔离
    # ======================

    cost_governance_service.set_budget(
        tenant_id=tenant_b,
        budget=0.0,
        updated_by="admin_B",
    )

    # A 已恢复预算，B 超限互不影响
    assert cost_governance_service.check_quota(tenant_a)["allowed"] is True

    assert cost_governance_service.check_quota(tenant_b)["allowed"] is False

    usage_a = cost_governance_service.usage(tenant_a)

    usage_b = cost_governance_service.usage(tenant_b)

    assert usage_a["today"]["requests"] == 2

    assert usage_b["today"]["requests"] == 0

    print("场景4 ✅ 跨租户隔离（预算/用量互不影响）")

    # ======================
    # 场景5：HTTP API
    # ======================

    from fastapi.testclient import TestClient

    from work_agent.main import app

    client = TestClient(app)

    login = client.post(
        "/api/admin/auth/login",
        json={"username": "admin_A", "password": "test123"},
    )

    headers = {
        "Authorization": f"Bearer {login.json()['access_token']}"
    }

    usage_api = client.get(
        "/api/admin/cost/usage",
        headers=headers,
    )

    assert usage_api.status_code == 200, usage_api.text

    assert usage_api.json()["today"]["requests"] == 2, usage_api.json()

    budget_get = client.get(
        "/api/admin/cost/budget",
        headers=headers,
    )

    assert budget_get.status_code == 200, budget_get.text

    budget_put = client.put(
        "/api/admin/cost/budget",
        json={"budget": 5.0},
        headers=headers,
    )

    assert budget_put.status_code == 200, budget_put.text

    assert budget_put.json()["budget"] == 5.0, budget_put.json()

    print("场景5 ✅ HTTP API（usage/budget get+put）")

    # ======================
    # 清理
    # ======================

    _cleanup()

    print("LLM Cost Governance 测试全部通过")


if __name__ == "__main__":

    test()
