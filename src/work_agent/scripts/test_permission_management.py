"""
知识库权限管理增强测试

验证：
- 修改权限后 Milvus 过滤结果变化（RAG metadata 同步）
- 支持部门/角色/指定用户
- 租户隔离（企业B不能修改企业A权限）

用法：
    python -m work_agent.scripts.test_permission_management
"""

import time

from fastapi.testclient import TestClient

from work_agent.core.container import document_service, rag_service
from work_agent.db.session import SessionLocal
from work_agent.main import app
from work_agent.repositories.document_repository import DocumentRepository
from work_agent.repositories.tenant_repository import TenantRepository
from work_agent.repositories.user_repository import UserRepository
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


def _user_by_wechat(wechat_id: str):

    db = SessionLocal()

    try:

        return UserRepository().get_by_wechat_user_id(
            db,
            wechat_id
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


def _search_doc(
        tenant_id: str,
        user_id: int,
        department: str,
        role: str,
        query: str
) -> list:

    meta = rag_service.search_with_meta(
        query,
        top_k=5,
        user_context={
            "tenant_id": tenant_id,
            "user_id": user_id,
            "department": department,
            "role": role,
        },
    )

    return meta["results"], meta["denied"]


def _search_allow(
        tenant_id: str,
        user_id: int,
        department: str,
        role: str,
        query: str,
        timeout: float = 15.0
) -> list:

    """
    检索并等待「不被权限拒绝」

    Milvus 权限更新（update_document_access: upsert+flush）后，
    读取侧可能有一小段可见延迟；CI 慢环境偶发读到旧 metadata 导致误判 denied。
    这里做有界重试吸收该延迟（有界：超时后返回最后一次结果，断言仍会明确失败）。
    """

    start = time.time()

    while True:

        results, denied = _search_doc(
            tenant_id, user_id, department, role, query,
        )

        if not denied or time.time() - start > timeout:

            return results

        time.sleep(1)


def _cleanup_tenant_docs():

    """
    清理历史测试残留（DB + Milvus 孤儿向量），避免污染基线
    """

    from work_agent.scripts.test_utils import cleanup_tenant_data

    cleanup_tenant_data()


def test():

    seed_tenants()

    _cleanup_tenant_docs()

    tenant_a_id = _tenant_id_by_corp("ww_corp_A")

    a_finance = _user_by_wechat("wx_A_finance")

    a_dev = _user_by_wechat("wx_A_dev")

    query = "采购审批制度是什么"

    client = TestClient(app)

    # ======================
    # 上传企业A采购审批制度（仅财务部/财务人员可见）
    # ======================

    # 真实长度制度文本（多段落；避免过短单句导致 Milvus 检索对可见性延迟敏感）
    content = (
        "采购审批制度：为规范企业采购流程，加强采购管理，控制采购成本，特制定本制度。\n"
        "第一条 采购申请。各部门根据实际业务需求填写采购申请单，"
        "注明采购物品名称、规格型号、数量、预算金额及用途说明，由部门负责人审核。\n"
        "第二条 询价比价。采购需进行询价比价，至少获取三家供应商报价，"
        "填写比价单并附供应商报价单，确保采购价格合理、透明。\n"
        "第三条 审批权限。采购金额在一万元以下由部门经理审批；"
        "一万元至五万元由财务经理审批；五万元以上由总经理办公会审批。\n"
        "第四条 合同签订。审批通过后由采购部门与供应商签订采购合同，"
        "合同条款需经法务部门审核，明确交付时间、质量标准与付款方式。\n"
        "第五条 验收付款。采购物品到货后由申请部门组织验收，"
        "验收合格后凭发票、验收单按合同约定办理付款手续。\n"
        "第六条 档案管理。采购全流程单据包括申请单、比价单、合同、验收单、发票，"
        "由行政部统一归档保存，保存期限不少于三年。\n"
        "本制度自发布之日起执行，由行政部负责解释。"
    )

    doc = document_service.upload(
        filename="采购审批制度.md",
        data=content.encode("utf-8"),
        category="采购管理",
        uploader="admin_A",
        tenant_id=tenant_a_id,
        visibility="restricted",
        departments=["财务部"],
        roles=["财务人员"],
    )

    _wait_ready(doc.id)

    # ======================
    # 基线：财务员工可检索，研发员工被过滤
    # ======================

    results_finance, denied_finance = _search_doc(
        tenant_a_id, a_finance.id, "财务部", "员工", query
    )

    assert any(
        "采购审批" in r["source"]
        for r in results_finance
    ), "基线失败: 财务员工应可检索"

    results_dev, denied_dev = _search_doc(
        tenant_a_id, a_dev.id, "研发部", "员工", query
    )

    assert denied_dev, "基线失败: 研发员工应被权限过滤"

    print("基线 ✅ 财务员工可检索 / 研发员工被过滤")

    # ======================
    # 修改权限：加入研发部 → Milvus 同步后研发员工可检索
    # ======================

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

    resp = client.put(
        f"/api/admin/documents/{doc.id}/permissions",
        headers=headers_a,
        json={
            "visibility": "restricted",
            "departments": ["财务部", "研发部"],
            "roles": ["财务人员"],
            "user_ids": [],
        },
    )

    assert resp.status_code == 200, resp.text

    updated = resp.json()

    assert "研发部" in updated["departments"], updated

    assert updated["synced_chunks"] >= 1, updated

    results_dev = _search_allow(
        tenant_a_id, a_dev.id, "研发部", "员工", query
    )

    assert any(
        "采购审批" in r["source"]
        for r in results_dev
    ), "场景2失败: 未检索到文档"

    print("场景2 ✅ 修改权限(加入研发部) → Milvus 同步, 研发员工可检索")

    # ======================
    # 指定用户：仅授权研发员工本人
    # ======================

    resp = client.put(
        f"/api/admin/documents/{doc.id}/permissions",
        headers=headers_a,
        json={
            "visibility": "restricted",
            "departments": [],
            "roles": [],
            "user_ids": [a_dev.id],
        },
    )

    assert resp.status_code == 200, resp.text

    results_dev = _search_allow(
        tenant_a_id, a_dev.id, "研发部", "员工", query
    )

    assert results_dev, "场景3失败: 指定用户应可检索"

    print("场景3 ✅ 指定用户授权 → 研发员工可检索")

    # ======================
    # 租户隔离：企业B不能修改企业A权限
    # ======================

    resp = client.post(
        "/api/admin/auth/login",
        json={
            "username": "admin_B",
            "password": "test123"
        }
    )

    headers_b = {
        "Authorization": f"Bearer {resp.json()['access_token']}"
    }

    resp = client.put(
        f"/api/admin/documents/{doc.id}/permissions",
        headers=headers_b,
        json={
            "visibility": "public",
            "departments": [],
            "roles": [],
            "user_ids": [],
        },
    )

    assert resp.status_code == 403, f"场景4失败: {resp.status_code}"

    print("场景4 ✅ 企业B修改企业A权限 → 403")

    # ======================
    # GET 权限端点
    # ======================

    resp = client.get(
        f"/api/admin/documents/{doc.id}/permissions",
        headers=headers_a,
    )

    assert resp.status_code == 200, resp.text

    perm = resp.json()

    assert perm["visibility"] == "restricted", perm

    assert perm["user_ids"] == [a_dev.id], perm

    print(f"场景5 ✅ GET 权限端点: {perm}")

    # ======================
    # 清理
    # ======================

    document_service.delete(
        doc.id,
        tenant_id=tenant_a_id,
    )

    print("权限管理测试全部通过")


if __name__ == "__main__":

    test()
