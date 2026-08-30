"""
Agent 智能体完整测试（Phase 4-7）

场景1：普通知识查询（IntentRouter + KnowledgeTool + Audit）
场景2：权限不足知识查询（RBAC + PermissionFilter + Audit denied）
场景3：文档操作请求（Tool Router）
场景4：LLM 异常（fallback）
场景5：跨租户攻击（tenant isolation）

用法：
    python -m work_agent.scripts.test_agent_intelligence
"""

import time

from work_agent.agent.llm import get_llm
from work_agent.agent.router.intent_router import IntentRouter
from work_agent.agent.runtime import AgentRuntime
from work_agent.agent.schemas import IntentType
from work_agent.core.container import document_service
from work_agent.db.models import AgentLog, Conversation, Document
from work_agent.db.session import SessionLocal
from work_agent.repositories.document_repository import DocumentRepository
from work_agent.repositories.tenant_repository import TenantRepository
from work_agent.repositories.user_repository import UserRepository
from work_agent.scripts.seed_tenants import seed_tenants


class _FakeFailingLLM:

    """
    模拟 LLM 不可用（测试 fallback）
    """

    def invoke(self, prompt):
        raise RuntimeError("LLM 服务不可用")


def _tenant_id(corp_id: str) -> str:

    db = SessionLocal()

    try:

        return str(
            TenantRepository().get_by_corp_id(db, corp_id).id
        )

    finally:

        db.close()


def _cleanup():

    from work_agent.scripts.test_utils import cleanup_tenant_data

    cleanup_tenant_data()

    db = SessionLocal()

    try:

        db.query(Conversation).delete(synchronize_session=False)

        db.commit()

    finally:

        db.close()


def _wait_ready(doc_id: int, timeout: float = 60.0):

    db = SessionLocal()

    try:

        start = time.time()

        while time.time() - start < timeout:

            db.expire_all()

            doc = DocumentRepository().get_by_id(db, doc_id)

            if doc and doc.status in ("ready", "failed"):
                return doc.status

            time.sleep(1)

        return "timeout"

    finally:

        db.close()


def _user(username: str):

    db = SessionLocal()

    try:

        return UserRepository().get_by_username(db, username)

    finally:

        db.close()


def _latest_log():

    db = SessionLocal()

    try:

        return (
            db.query(AgentLog)
            .order_by(AgentLog.id.desc())
            .first()
        )

    finally:

        db.close()


def test():

    seed_tenants()

    _cleanup()

    tenant_a_id = _tenant_id("ww_corp_A")

    tenant_b_id = _tenant_id("ww_corp_B")

    # ======================
    # 准备：租户A受限文档 + 租户B文档
    # ======================

    finance = (
        "财务报销制度：差旅报销需提交发票，"
        "超标需审批。"
    ).encode("utf-8")

    doc_a = document_service.upload(
        filename="财务报销制度.md",
        data=finance,
        category="财务管理",
        uploader="admin_A",
        tenant_id=tenant_a_id,
        visibility="restricted",
        departments=["财务部"],
        roles=["财务人员"],
    )

    doc_b = document_service.upload(
        filename="企业B机密制度.md",
        data="企业B专属机密制度内容，仅企业B可见".encode("utf-8"),
        category="测试",
        uploader="admin_B",
        tenant_id=tenant_b_id,
        visibility="public",
    )

    _wait_ready(doc_a.id)

    _wait_ready(doc_b.id)

    user_normal = _user("员工A")

    user_dev = _user("A研发员工")

    admin_a = _user("admin_A")

    runtime = AgentRuntime()

    # ======================
    # 场景1：普通知识查询
    # ======================

    r1 = runtime.execute(
        message="财务报销制度是什么",
        user=user_normal,
        channel="wechat",
    )

    assert r1["intent"] == IntentType.KNOWLEDGE_QUERY, r1["intent"]

    assert "报销" in r1["response"], r1["response"]

    assert r1["tools_called"] == ["knowledge_tool"], r1["tools_called"]

    assert r1["permission_denied"] is False, r1

    log1 = _latest_log()

    assert log1.status == "success", log1.status

    assert log1.intent_confidence > 0.5, log1.intent_confidence

    assert log1.tools_called == ["knowledge_tool"], log1.tools_called

    print(
        f"场景1 ✅ 普通知识查询: intent={r1['intent']}, "
        f"confidence={log1.intent_confidence}, tools={log1.tools_called}"
    )

    # ======================
    # 场景2：权限不足知识查询
    # ======================

    r2 = runtime.execute(
        message="财务报销制度是什么",
        user=user_dev,
        channel="wechat",
    )

    assert r2["permission_denied"] is True, r2

    log2 = _latest_log()

    assert log2.status == "denied", log2.status

    print("场景2 ✅ 权限不足知识查询 → denied 审计")

    # ======================
    # 场景3：文档操作请求（Tool Router）
    # ======================

    r3 = runtime.execute(
        message=f"删除文档{doc_a.id}",
        user=admin_a,
        channel="wechat",
    )

    assert r3["intent"] == IntentType.DOCUMENT_OPERATION, r3["intent"]

    assert r3["tools_called"] == ["document_tool"], r3["tools_called"]

    assert "已删除" in r3["response"], r3["response"]

    print(
        f"场景3 ✅ 文档操作请求: tools={r3['tools_called']}, "
        f"response={r3['response'][:40]}"
    )

    # ======================
    # 场景4：LLM 异常 → fallback
    # ======================

    fallback_router = IntentRouter(
        llm=_FakeFailingLLM()
    )

    runtime_fallback = AgentRuntime(
        intent_router=fallback_router,
    )

    r4 = runtime_fallback.execute(
        message="财务报销制度是什么",
        user=user_normal,
        channel="wechat",
    )

    assert r4["intent"] == IntentType.KNOWLEDGE_QUERY, r4["intent"]

    assert r4["response"], r4["response"]

    print(
        f"场景4 ✅ LLM 异常 → 规则回退: intent={r4['intent']}, "
        f"response_len={len(r4['response'])}"
    )

    # ======================
    # 场景5：跨租户攻击
    # ======================

    # 5a：企业A用户检索不到企业B文档（B文档内容不泄漏）
    r5a = runtime.execute(
        message="企业B专属机密制度内容是什么",
        user=user_dev,
        channel="wechat",
    )

    # B 文档独特内容不应出现在回复中
    assert "仅企业B可见" not in r5a["response"], r5a["response"]

    # 5b：企业A管理员删除企业B文档 → 干净拒绝（非500）
    r5b = runtime.execute(
        message=f"删除文档{doc_b.id}",
        user=admin_a,
        channel="wechat",
    )

    assert r5b["permission_denied"] is True, r5b

    assert "权限不足" in r5b["response"], r5b["response"]

    # 5c：确认企业B文档未被删除
    db = SessionLocal()

    try:

        doc_b_exists = db.get(Document, doc_b.id) is not None

    finally:

        db.close()

    assert doc_b_exists, "跨租户删除不应成功"

    print("场景5 ✅ 跨租户攻击：A查不到B文档 / A删B文档→拒绝 / B文档未被删除")

    # ======================
    # 清理
    # ======================

    document_service.delete(doc_b.id, tenant_id=tenant_b_id)

    _cleanup()

    print("Agent 智能体测试全部通过")


if __name__ == "__main__":

    test()
