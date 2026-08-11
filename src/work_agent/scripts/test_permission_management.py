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

from pathlib import Path

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

    data = Path(
        "knowledge/采购审批制度.md"
    ).read_bytes()

    doc = document_service.upload(
        filename="采购审批制度.md",
        data=data,
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

    results_dev, denied_dev = _search_doc(
        tenant_a_id, a_dev.id, "研发部", "员工", query
    )

    assert not denied_dev, "场景2失败: 加入研发部后研发员工应可检索"

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

    results_dev, denied_dev = _search_doc(
        tenant_a_id, a_dev.id, "研发部", "员工", query
    )

    assert not denied_dev, "场景3失败: 指定用户应可检索"

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
