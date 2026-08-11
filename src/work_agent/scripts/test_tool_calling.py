"""
Tool Calling 测试

验证：
- 工具注册表（4 个工具）
- document_operation 路由到 document_tool
- 权限强制（无权限 → permission_denied）
- permission_tool 权限修改
- 选择器回退

用法：
    python -m work_agent.scripts.test_tool_calling
"""

import time

from work_agent.agent.context import AgentContext
from work_agent.agent.runtime import agent_runtime
from work_agent.agent.schemas import IntentType
from work_agent.agent.tools.registry import tool_registry
from work_agent.agent.tools.selector import tool_selector
from work_agent.core.container import document_service
from work_agent.db.models import Document
from work_agent.db.session import SessionLocal
from work_agent.repositories.document_repository import DocumentRepository
from work_agent.repositories.tenant_repository import TenantRepository
from work_agent.repositories.user_repository import UserRepository
from work_agent.scripts.seed_tenants import seed_tenants
from work_agent.services.rbac_service import RBACService


def _tenant_id(corp_id: str) -> str:

    db = SessionLocal()

    try:

        return str(
            TenantRepository().get_by_corp_id(db, corp_id).id
        )

    finally:

        db.close()


def _cleanup_tenant_docs():

    from work_agent.scripts.test_utils import cleanup_tenant_data

    cleanup_tenant_data()


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


def test():

    seed_tenants()

    _cleanup_tenant_docs()

    tenant_a_id = _tenant_id("ww_corp_A")

    db = SessionLocal()

    try:

        admin = UserRepository().get_by_username(db, "admin_A")

        user = UserRepository().get_by_username(db, "A财务员工")

        admin_perms = RBACService().get_permission_codes(db, admin.id)

        user_perms = RBACService().get_permission_codes(db, user.id)

    finally:

        db.close()

    # ======================
    # 场景1：工具注册表
    # ======================

    tools = tool_registry.list_tools()

    tool_names = {t["name"] for t in tools}

    assert {
        "knowledge_tool",
        "document_tool",
        "permission_tool",
        "audit_tool",
    } <= tool_names, tool_names

    print(f"场景1 ✅ 工具注册表: {sorted(tool_names)}")

    # ======================
    # 场景2：document_operation → document_tool
    # ======================

    # 上传租户A测试文档
    doc = document_service.upload(
        filename="tool_test.md",
        data="工具测试文档内容".encode("utf-8"),
        category="测试",
        uploader="admin_A",
        tenant_id=tenant_a_id,
        visibility="public",
    )

    _wait_ready(doc.id)

    # 确定性验证 document_tool.list（经 OperationAgent，避免 LLM 意图分类不确定性）
    from work_agent.agent.agents.registry import agent_registry as registry
    from work_agent.agent.context import AgentContext
    from work_agent.agent.schemas import PlanResult, PlanStep

    db = SessionLocal()

    try:

        admin_perms = RBACService().get_permission_codes(db, admin.id)

    finally:

        db.close()

    ctx = AgentContext.build(
        user=admin,
        permissions=admin_perms,
    )

    op_agent = registry.get("operation_agent")

    agent_result = op_agent.run(
        context=ctx,
        plan=PlanResult(
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
        ),
        message="查看知识库文档列表",
    )

    assert "tool_test.md" in agent_result.response, agent_result.response

    assert agent_result.permission_denied is False, agent_result

    print("场景2 ✅ document_tool.list（含文档列表）")

    # ======================
    # 场景3：权限强制（USER 无 document:delete）
    # ======================

    result = agent_runtime.execute(
        message=f"删除文档{doc.id}",
        user=user,
        channel="wechat",
    )

    assert result["intent"] == IntentType.DOCUMENT_OPERATION, result["intent"]

    assert result["permission_denied"] is True, result

    assert "权限不足" in result["response"], result["response"]

    print("场景3 ✅ 权限强制: USER 删除文档 → permission_denied")

    # ======================
    # 场景4：permission_tool 权限修改（admin_A 有 document:permission_manage）
    # ======================

    result = agent_runtime.execute(
        message=f"把文档{doc.id}权限改成研发部可见",
        user=admin,
        channel="wechat",
    )

    assert result["intent"] == IntentType.DOCUMENT_OPERATION, result["intent"]

    assert result["permission_denied"] is False, result

    assert "研发部" in result["response"], result["response"]

    print("场景4 ✅ permission_tool 权限修改成功")

    # ======================
    # 场景5：选择器回退
    # ======================

    ctx = AgentContext.build(
        user=admin,
        permissions=admin_perms,
    )

    selection = tool_selector.select(
        intent=IntentType.DOCUMENT_OPERATION,
        entities={"action": "delete", "document_ref": "5"},
        message="删除文档5",
        context=ctx,
    )

    assert selection["tool"] == "document_tool", selection

    assert selection["action"] == "delete", selection

    print(f"场景5 ✅ 选择器回退: {selection}")

    # ======================
    # 清理
    # ======================

    document_service.delete(doc.id, tenant_id=tenant_a_id)

    print("Tool Calling 测试全部通过")


if __name__ == "__main__":

    test()
