"""
Prompt Governance 测试（P5-5-3）

覆盖：
- 文件基线 seed
- 创建草稿（版本自增）
- 审批 → 激活覆盖文件（PromptManager 解析 DB 版本）
- 回滚
- 审计落库（prompt.activate）
- 租户隔离
- HTTP API

用法：
    python -m work_agent.scripts.test_prompt_governance
"""

from work_agent.core.container import prompt_governance_service
from work_agent.core.prompt_manager import prompt_manager
from work_agent.db.models import OperationLog, PromptVersion
from work_agent.db.session import SessionLocal
from work_agent.scripts.seed_tenants import seed_tenants


TEST_PROMPT = "intent_router"

DRAFT_CONTENT = "这是治理后的全新 Intent Router Prompt 内容。"


def _cleanup():

    db = SessionLocal()

    try:

        db.query(PromptVersion).delete(
            synchronize_session=False
        )

        db.commit()

    finally:

        db.close()

    prompt_manager.clear_cache()


def _operation_count(action: str) -> int:

    db = SessionLocal()

    try:

        return (
            db.query(OperationLog)
            .filter(OperationLog.action == action)
            .count()
        )

    finally:

        db.close()


def test():

    seed_tenants()

    _cleanup()

    # ======================
    # 场景1：文件基线 seed + PromptManager 解析 DB 版本
    # ======================

    seeded = prompt_governance_service.seed_from_files()

    assert seeded >= 1, seeded

    active = prompt_governance_service.get_active(TEST_PROMPT)

    assert active is not None

    assert active.version == "1.0"

    # PromptManager 解析到 DB active 版本（内容与文件一致）
    loaded = prompt_manager.load(TEST_PROMPT)

    assert loaded["version"] == "1.0", loaded["version"]

    assert loaded["content"] == active.content, "应解析到 DB 版本"

    print(f"场景1 ✅ 文件基线 seed（{seeded} 个 Prompt）+ PromptManager 解析 DB 版本")

    # ======================
    # 场景2：创建草稿 → 审批 → 激活覆盖文件
    # ======================

    draft = prompt_governance_service.create_draft(
        name=TEST_PROMPT,
        content=DRAFT_CONTENT,
        description="治理测试草稿",
        updated_by="admin",
    )

    assert draft["status"] == "draft", draft

    assert draft["version"] == "1.1", draft["version"]

    approved = prompt_governance_service.approve(
        name=TEST_PROMPT,
        version=draft["version"],
        updated_by="admin",
    )

    assert approved["status"] == "approved", approved

    activated = prompt_governance_service.activate(
        name=TEST_PROMPT,
        version=draft["version"],
        updated_by="admin",
        audit_tenant_id="1",
        audit_user_id=1,
    )

    assert activated["status"] == "active", activated

    # 激活后 PromptManager 立即解析新版本（缓存已清）
    reloaded = prompt_manager.load(TEST_PROMPT)

    assert reloaded["version"] == "1.1", reloaded["version"]

    assert reloaded["content"] == DRAFT_CONTENT, reloaded["content"]

    print("场景2 ✅ 草稿→审批→激活覆盖文件（PromptManager 解析新版本）")

    # ======================
    # 场景3：回滚到旧版本
    # ======================

    rollback = prompt_governance_service.activate(
        name=TEST_PROMPT,
        version="1.0",
        updated_by="admin",
        audit_tenant_id="1",
        audit_user_id=1,
    )

    assert rollback["version"] == "1.0", rollback

    rolled = prompt_manager.load(TEST_PROMPT)

    assert rolled["version"] == "1.0", rolled["version"]

    # 1.1 已 deprecated
    history = prompt_governance_service.list_history(TEST_PROMPT)

    status_map = {
        item["version"]: item["status"]
        for item in history
    }

    assert status_map["1.1"] == "deprecated", status_map

    print("场景3 ✅ 回滚（1.0 重新激活，1.1 deprecated）")

    # ======================
    # 场景4：审计落库
    # ======================

    before = _operation_count("prompt.activate")

    prompt_governance_service.activate(
        name=TEST_PROMPT,
        version="1.1",
        updated_by="admin",
        audit_tenant_id="1",
        audit_user_id=1,
    )

    after = _operation_count("prompt.activate")

    assert after == before + 1, (before, after)

    print("场景4 ✅ 激活审计落库（prompt.activate）")

    # ======================
    # 场景5：租户隔离（租户级草稿不影响平台 active）
    # ======================

    tenant_a = "1"

    tenant_b = "2"

    prompt_governance_service.create_draft(
        name=TEST_PROMPT,
        content="租户B专属Prompt",
        description="",
        updated_by="admin_B",
        tenant_id=tenant_b,
    )

    # 平台 active 不受租户 B 草稿影响
    platform_active = prompt_governance_service.get_active(
        TEST_PROMPT,
        tenant_id="",
    )

    assert platform_active.version == "1.1", platform_active.version

    # 租户 A/B 历史互不干扰
    history_a = prompt_governance_service.list_history(
        TEST_PROMPT,
        tenant_id=tenant_a,
    )

    history_b = prompt_governance_service.list_history(
        TEST_PROMPT,
        tenant_id=tenant_b,
    )

    assert any(
        "租户B" in item["content"]
        for item in history_b
    )

    assert all(
        "租户B" not in item["content"]
        for item in history_a
    )

    print("场景5 ✅ 租户隔离（B 租户草稿不影响平台 active）")

    # ======================
    # 场景6：HTTP API
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

    # 清单
    listing = client.get(
        "/api/admin/prompts",
        headers=headers,
    )

    assert listing.status_code == 200, listing.text

    names = {item["name"] for item in listing.json()}

    assert TEST_PROMPT in names, names

    # 历史
    hist = client.get(
        f"/api/admin/prompts/{TEST_PROMPT}/history",
        headers=headers,
    )

    assert hist.status_code == 200, hist.text

    # 创建草稿 API
    created = client.post(
        f"/api/admin/prompts/{TEST_PROMPT}/versions",
        json={
            "content": "HTTP API 草稿内容",
            "description": "API测试",
        },
        headers=headers,
    )

    assert created.status_code == 200, created.text

    assert created.json()["status"] == "draft", created.json()

    # 激活 API
    activated_api = client.post(
        f"/api/admin/prompts/{TEST_PROMPT}/activate",
        json={"version": created.json()["version"]},
        headers=headers,
    )

    assert activated_api.status_code == 200, activated_api.text

    print("场景6 ✅ HTTP API（清单/历史/草稿/激活）")

    # ======================
    # 清理
    # ======================

    _cleanup()

    print("Prompt Governance 测试全部通过")


if __name__ == "__main__":

    test()
