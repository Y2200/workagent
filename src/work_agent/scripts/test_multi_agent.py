"""
Multi Agent 架构测试（P5-2）

覆盖：
- 知识 Agent
- 操作 Agent
- 分析 Agent
- 权限拒绝
- 跨租户隔离

用法：
    python -m work_agent.scripts.test_multi_agent
"""

import time

from work_agent.agent.agents.registry import agent_registry
from work_agent.agent.runtime import agent_runtime
from work_agent.core.container import document_service
from work_agent.db.models import Conversation, Document
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


def test():

    seed_tenants()

    _cleanup()

    tenant_a_id = _tenant_id("ww_corp_A")

    tenant_b_id = _tenant_id("ww_corp_B")

    # ======================
    # 场景0：Agent 注册表
    # ======================

    agents = agent_registry.list_agents()

    names = {a["name"] for a in agents}

    assert {
        "knowledge_agent",
        "operation_agent",
        "analysis_agent",
    } <= names, names

    print(f"场景0 ✅ Agent 注册表: {sorted(names)}")

    # ======================
    # 准备：租户A受限文档 + 租户B文档
    # ======================

    doc_a = document_service.upload(
        filename="财务报销制度.md",
        data=(
            "财务报销制度：差旅报销需提交发票，"
            "超标需审批，报销流程见附件。"
        ).encode("utf-8"),
        category="财务管理",
        uploader="admin_A",
        tenant_id=tenant_a_id,
        visibility="restricted",
        departments=["财务部"],
        roles=["财务人员"],
    )

    doc_b = document_service.upload(
        filename="企业B机密.md",
        data="企业B专属机密内容，仅企业B可见".encode("utf-8"),
        category="测试",
        uploader="admin_B",
        tenant_id=tenant_b_id,
        visibility="public",
    )

    _wait_ready(doc_a.id)

    _wait_ready(doc_b.id)

    user_normal = _user("员工A")

    user_dev = _user("A研发员工")

    user_finance = _user("A财务员工")

    admin_a = _user("admin_A")

    # ======================
    # 场景1：知识 Agent
    # ======================

    r1 = agent_runtime.execute(
        message="财务报销制度是什么",
        user=user_normal,
        channel="wechat",
    )

    assert r1["tools_called"] == ["knowledge_tool"], r1["tools_called"]

    assert "报销" in r1["response"], r1["response"]

    assert r1["permission_denied"] is False, r1

    print("场景1 ✅ 知识 Agent")

    # ======================
    # 场景2：操作 Agent（直接验证，确定性）
    # ======================

    from work_agent.agent.agents.registry import agent_registry as registry
    from work_agent.agent.context import AgentContext
    from work_agent.agent.schemas import PlanResult, PlanStep
    from work_agent.services.rbac_service import RBACService

    op_agent = registry.get("operation_agent")

    assert op_agent is not None

    db = SessionLocal()

    try:

        admin_perms = RBACService().get_permission_codes(db, admin_a.id)

    finally:

        db.close()

    ctx = AgentContext.build(
        user=admin_a,
        permissions=admin_perms,
    )

    plan_doc = PlanResult(
        kind="document",
        intent="document_operation",
        steps=[
            PlanStep(
                step_id=1,
                tool="document_tool",
                action="list",
                args={},
            ),
        ],
    )

    agent_result = op_agent.run(
        context=ctx,
        plan=plan_doc,
        message="查看知识库文档列表",
    )

    assert agent_result.tools_called == ["document_tool"], agent_result.tools_called

    assert "财务报销制度.md" in agent_result.response, agent_result.response

    print("场景2 ✅ 操作 Agent（document_tool.list 返回文档列表）")

    # ======================
    # 场景3：分析 Agent
    # ======================

    r3 = agent_runtime.execute(
        message="项目延期了3天，有风险",
        user=user_normal,
        channel="wechat",
    )

    assert r3["tools_called"] == ["analysis_tool"], r3["tools_called"]

    assert "风险分析" in r3["response"], r3["response"]

    print("场景3 ✅ 分析 Agent")

    # ======================
    # 场景4：权限拒绝
    # ======================

    # A财务员工（USER，无 document:delete）删除文档
    r4 = agent_runtime.execute(
        message=f"删除文档{doc_a.id}",
        user=user_finance,
        channel="wechat",
    )

    assert r4["permission_denied"] is True, r4

    assert any(
        kw in r4["response"]
        for kw in ("权限不足", "权限")
    ), r4["response"]

    print("场景4 ✅ 权限拒绝（USER 删除 → permission_denied）")

    # ======================
    # 场景5：跨租户隔离
    # ======================

    # 5a：企业A用户检索不到企业B文档内容
    r5a = agent_runtime.execute(
        message="企业B专属机密内容是什么",
        user=user_dev,
        channel="wechat",
    )

    assert "仅企业B可见" not in r5a["response"], r5a["response"]

    # 5b：企业A管理员删除企业B文档 → 拒绝
    r5b = agent_runtime.execute(
        message=f"删除文档{doc_b.id}",
        user=admin_a,
        channel="wechat",
    )

    assert r5b["permission_denied"] is True, r5b

    print("场景5 ✅ 跨租户隔离（A查不到B文档 / A删B文档→拒绝）")

    # ======================
    # 清理
    # ======================

    document_service.delete(doc_a.id, tenant_id=tenant_a_id)

    document_service.delete(doc_b.id, tenant_id=tenant_b_id)

    _cleanup()

    print("Multi Agent 测试全部通过")


if __name__ == "__main__":

    test()
