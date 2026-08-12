"""
Agent Configuration Center 测试（P5-5-2）

覆盖：
- 内置默认值
- 租户覆盖优先于平台/默认
- 工具停用拦截（Runtime 不执行 Agent）
- 平台级配置仅 SUPER_ADMIN
- 跨租户隔离
- 缓存失效
- top_k 配置生效

用法：
    python -m work_agent.scripts.test_agent_config
"""

from work_agent.config import settings
from work_agent.core.container import (
    agent_config_service,
    document_service,
)
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


def _cleanup_configs():

    db = SessionLocal()

    try:

        db.query(AgentConfig).delete(
            synchronize_session=False
        )

        db.commit()

    finally:

        db.close()

    agent_config_service._cache.clear()


def test():

    seed_tenants()

    _cleanup_configs()

    tenant_a = _tenant_id("ww_corp_A")

    tenant_b = _tenant_id("ww_corp_B")

    # ======================
    # 场景1：内置默认值
    # ======================

    assert agent_config_service.get(
        "agent.default_top_k",
        tenant_a,
    ) == 5

    assert agent_config_service.get(
        "cost.monthly_budget",
        tenant_a,
    ) is None

    assert agent_config_service.is_tool_enabled(
        "knowledge_tool",
        tenant_a,
    ) is True

    print("场景1 ✅ 内置默认值")

    # ======================
    # 场景2：租户覆盖优先 + 跨租户隔离
    # ======================

    agent_config_service.set(
        key="agent.default_top_k",
        value=8,
        tenant_id=tenant_a,
        updated_by="admin_A",
    )

    assert agent_config_service.get(
        "agent.default_top_k",
        tenant_a,
    ) == 8

    # 租户 B 不受影响
    assert agent_config_service.get(
        "agent.default_top_k",
        tenant_b,
    ) == 5

    # 平台级设置 → 两租户都生效
    agent_config_service.set(
        key="agent.default_top_k",
        value=3,
        tenant_id="",
        updated_by="admin",
    )

    # 缓存失效后租户 A 仍优先取自身覆盖
    assert agent_config_service.get(
        "agent.default_top_k",
        tenant_a,
    ) == 8

    assert agent_config_service.get(
        "agent.default_top_k",
        tenant_b,
    ) == 3

    print("场景2 ✅ 租户覆盖优先 + 平台默认 + 隔离")

    # ======================
    # 场景3：top_k 配置驱动规划器
    # ======================

    from work_agent.agent.planner import AgentPlanner
    from work_agent.agent.schemas import IntentResult, IntentType
    from work_agent.agent.context import AgentContext

    user_a = _user("A财务员工")

    ctx = AgentContext.build(
        user=user_a,
        request_id="config-test",
    )

    intent = IntentResult(
        intent=IntentType.KNOWLEDGE_QUERY,
        confidence=1.0,
        entities={},
        need_tool=True,
        tool="knowledge_tool",
    )

    plan = AgentPlanner().plan(
        message="报销制度是什么",
        intent_result=intent,
        context=ctx,
    )

    assert plan.steps[0].args.get("top_k") == 8, plan.steps[0].args

    print("场景3 ✅ 配置中心 top_k 驱动规划器")

    # ======================
    # 场景4：工具停用拦截（Runtime 不执行 Agent）
    # ======================

    agent_config_service.set(
        key="agent.tools.enabled",
        value=["knowledge_tool"],
        tenant_id=tenant_a,
        updated_by="admin_A",
    )

    from work_agent.agent.agents.schemas import AgentResult
    from work_agent.agent.planner import AgentPlanner
    from work_agent.agent.runtime import AgentRuntime
    from work_agent.agent.schemas import IntentResult, IntentType

    class FixedIntentRouter:

        last_prompt_version = ""

        def route(
                self,
                message,
                user_context=None,
                tenant_context=None
        ):
            return IntentResult(
                intent=IntentType.DOCUMENT_OPERATION,
                confidence=1.0,
                entities={"action": "list"},
                need_tool=True,
                tool="document_tool",
            )

    class FixedSelector:

        last_prompt_version = ""

        def select(
                self,
                *,
                intent,
                entities,
                message,
                context
        ):
            return {
                "tool": "document_tool",
                "action": "list",
                "args": {},
            }

    class RecordingSupervisor:

        def __init__(self):
            self.called = False

        def dispatch(
                self,
                **kwargs
        ):
            self.called = True
            return AgentResult(
                agent="operation_agent",
                response="不应到达这里",
                intent=IntentType.DOCUMENT_OPERATION,
            )

    supervisor = RecordingSupervisor()

    runtime = AgentRuntime(
        intent_router=FixedIntentRouter(),
        supervisor=supervisor,
        planner=AgentPlanner(selector=FixedSelector()),
    )

    admin_a = _user("admin_A")

    result = runtime.execute(
        message="查看知识库文档列表",
        user=admin_a,
        channel="test",
    )

    assert "工具已停用" in result["response"], result["response"]

    assert "document_tool" in result["response"], result["response"]

    # 停用拦截不执行 Agent
    assert supervisor.called is False, "停用工具不应分派 Agent"

    # 停用不调 LLM，无工具调用
    assert result.get("tools_called", []) == [], result

    print("场景4 ✅ 工具停用拦截（不执行 Agent）")

    # 恢复全部启用
    agent_config_service.set(
        key="agent.tools.enabled",
        value=None,
        tenant_id=tenant_a,
        updated_by="admin_A",
    )

    assert agent_config_service.is_tool_enabled(
        "document_tool",
        tenant_a,
    ) is True

    print("场景4b ✅ 恢复工具启用")

    # ======================
    # 场景5：HTTP API + 平台级权限
    # ======================

    from fastapi.testclient import TestClient

    from work_agent.main import app

    client = TestClient(app)

    def _headers(username, password="test123"):

        login = client.post(
            "/api/admin/auth/login",
            json={"username": username, "password": password},
        )

        return {
            "Authorization": f"Bearer {login.json()['access_token']}"
        }

    headers_a = _headers("admin_A")

    # 列表
    listing = client.get(
        "/api/admin/configs",
        headers=headers_a,
    )

    assert listing.status_code == 200, listing.text

    keys = {item["key"] for item in listing.json()}

    assert "agent.default_top_k" in keys, keys

    # 未知配置项 → 400
    bad = client.put(
        "/api/admin/configs/unknown.key",
        json={"value": 1},
        headers=headers_a,
    )

    assert bad.status_code == 400, bad.text

    # TENANT_ADMIN 修改平台级配置 → 403
    denied = client.put(
        "/api/admin/configs/agent.default_top_k",
        json={"value": 9, "scope": "platform"},
        headers=headers_a,
    )

    assert denied.status_code == 403, denied.text

    # SUPER_ADMIN 修改平台级配置 → 200
    headers_super = _headers(
        settings.admin_username,
        settings.admin_password,
    )

    ok = client.put(
        "/api/admin/configs/agent.default_top_k",
        json={"value": 7, "scope": "platform"},
        headers=headers_super,
    )

    assert ok.status_code == 200, ok.text

    configs_a = client.get(
        "/api/admin/configs",
        headers=headers_a,
    ).json()

    top_k_entry = next(
        item
        for item in configs_a
        if item["key"] == "agent.default_top_k"
    )

    # 租户 A 覆盖（8）仍优先于平台级（7）
    assert top_k_entry["value"] == 8, top_k_entry

    print("场景5 ✅ HTTP API + 平台级权限")

    # ======================
    # 清理
    # ======================

    _cleanup_configs()

    print("Agent Configuration Center 测试全部通过")


if __name__ == "__main__":

    test()
