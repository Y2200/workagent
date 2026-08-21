"""
Audit 智能体字段测试（P4-6）

验证 agent_logs 落库字段：
- agent_version / model_name / prompt_version / intent_confidence / tools_called

用法：
    python -m work_agent.scripts.test_audit_intelligence
"""

from work_agent.agent.runtime import agent_runtime
from work_agent.db.models import AgentLog
from work_agent.db.session import SessionLocal
from work_agent.repositories.user_repository import UserRepository
from work_agent.scripts.seed_tenants import seed_tenants


def test():

    seed_tenants()

    db = SessionLocal()

    try:

        user = UserRepository().get_by_username(db, "员工A")

    finally:

        db.close()

    # ======================
    # 知识查询路径（knowledge_tool）
    # ======================

    result = agent_runtime.execute(
        message="财务报销制度是什么",
        user=user,
        channel="wechat",
    )

    assert result.get("tools_called") == ["knowledge_tool"], result

    db = SessionLocal()

    try:

        log = (
            db.query(AgentLog)
            .order_by(AgentLog.id.desc())
            .first()
        )

        assert log is not None

        # 场景1：agent_version / model_name
        assert log.agent_version == "0.1.0", log.agent_version

        assert log.model_name, log.model_name

        # 场景2：prompt_version
        assert log.prompt_version == "1.1", log.prompt_version

        # 场景3：intent_confidence
        assert 0.0 <= log.intent_confidence <= 1.0, log.intent_confidence

        assert log.intent_confidence > 0.5, log.intent_confidence

        # 场景4：tools_called
        assert log.tools_called == ["knowledge_tool"], log.tools_called

        log_id = log.id

    finally:

        db.close()

    print(
        f"场景1-4 ✅ 审计智能体字段落库: "
        f"agent={log.agent_version}, model={log.model_name}, "
        f"prompt=v{log.prompt_version}, confidence={log.intent_confidence}, "
        f"tools={log.tools_called}"
    )

    # ======================
    # API 层可见（/logs 返回新字段）
    # ======================

    from fastapi.testclient import TestClient

    from work_agent.main import app

    client = TestClient(app)

    resp = client.post(
        "/api/admin/auth/login",
        json={
            "username": "admin",
            "password": "admin123"
        }
    )

    assert resp.status_code == 200, resp.text

    headers = {
        "Authorization": f"Bearer {resp.json()['access_token']}"
    }

    resp = client.get(
        "/api/admin/logs",
        headers=headers,
        params={"page_size": 5},
    )

    assert resp.status_code == 200, resp.text

    items = resp.json()["items"]

    assert any(
        item["id"] == log_id
        for item in items
    ), "日志应可在 API 查询"

    latest = next(
        item
        for item in items
        if item["id"] == log_id
    )

    assert latest["tools_called"] == ["knowledge_tool"], latest

    assert latest["intent_confidence"] > 0.5, latest

    print(
        f"场景5 ✅ /logs API 返回审计字段: "
        f"confidence={latest['intent_confidence']}, tools={latest['tools_called']}"
    )

    # 清理测试日志
    db = SessionLocal()

    try:

        db.query(AgentLog).filter(
            AgentLog.id == log_id
        ).delete(synchronize_session=False)

        db.commit()

    finally:

        db.close()

    print("Audit 智能体字段测试全部通过")


if __name__ == "__main__":

    test()
