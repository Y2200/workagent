"""
租户越权测试

场景：
1. 企业A管理员删除企业B文档 → 403
2. 企业A管理员查看企业B文档详情 → 403
3. 企业A只能看到自己的文档（列表不含企业B文档）
4. 各管理员可正常操作自己租户的文档 → 204

用法：
    python -m work_agent.scripts.test_tenant_admin
"""

import time

from fastapi.testclient import TestClient

from work_agent.db.session import SessionLocal
from work_agent.main import app
from work_agent.repositories.document_repository import DocumentRepository
from work_agent.repositories.tenant_repository import TenantRepository
from work_agent.scripts.seed_tenants import seed_tenants


def _tenant_id_by_corp(corp_id: str) -> str:

    db = SessionLocal()

    try:

        tenant = TenantRepository().get_by_corp_id(
            db,
            corp_id
        )

        return str(tenant.id)

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


def test():

    seed_tenants()

    client = TestClient(app)

    # ======================
    # 登录两个租户管理员
    # ======================

    resp = client.post(
        "/api/admin/auth/login",
        json={
            "username": "admin_A",
            "password": "test123"
        }
    )

    assert resp.status_code == 200, resp.text

    token_a = resp.json()["access_token"]

    headers_a = {
        "Authorization": f"Bearer {token_a}"
    }

    resp = client.post(
        "/api/admin/auth/login",
        json={
            "username": "admin_B",
            "password": "test123"
        }
    )

    assert resp.status_code == 200, resp.text

    token_b = resp.json()["access_token"]

    headers_b = {
        "Authorization": f"Bearer {token_b}"
    }

    # ======================
    # 上传各自租户文档
    # ======================

    resp = client.post(
        "/api/admin/documents/upload",
        headers=headers_a,
        files={
            "file": (
                "tenantA_policy.md",
                "企业A专属制度内容".encode("utf-8"),
                "text/markdown"
            )
        },
        data={
            "category": "测试"
        }
    )

    assert resp.status_code == 202, resp.text

    doc_a_id = resp.json()["id"]

    resp = client.post(
        "/api/admin/documents/upload",
        headers=headers_b,
        files={
            "file": (
                "tenantB_policy.md",
                "企业B专属制度内容".encode("utf-8"),
                "text/markdown"
            )
        },
        data={
            "category": "测试"
        }
    )

    assert resp.status_code == 202, resp.text

    doc_b_id = resp.json()["id"]

    _wait_ready(doc_a_id)

    _wait_ready(doc_b_id)

    # ======================
    # 场景1：企业A删除企业B文档 → 403
    # ======================

    resp = client.delete(
        f"/api/admin/documents/{doc_b_id}",
        headers=headers_a
    )

    assert resp.status_code == 403, f"场景1失败: {resp.status_code} {resp.text}"

    print("场景1 ✅ 企业A删除企业B文档 → 403")

    # ======================
    # 场景2：企业A查看企业B文档详情 → 403
    # ======================

    resp = client.get(
        f"/api/admin/documents/{doc_b_id}",
        headers=headers_a
    )

    assert resp.status_code == 403, f"场景2失败: {resp.status_code} {resp.text}"

    print("场景2 ✅ 企业A查看企业B文档详情 → 403")

    # ======================
    # 场景3：企业A只能看到自己的文档
    # ======================

    resp = client.get(
        "/api/admin/documents",
        headers=headers_a
    )

    assert resp.status_code == 200

    filenames_a = [
        doc["filename"]
        for doc in resp.json()
    ]

    assert "tenantA_policy.md" in filenames_a, filenames_a

    assert "tenantB_policy.md" not in filenames_a, filenames_a

    print(f"场景3 ✅ 企业A只见自己文档: {filenames_a}")

    resp = client.get(
        "/api/admin/documents",
        headers=headers_b
    )

    filenames_b = [
        doc["filename"]
        for doc in resp.json()
    ]

    assert "tenantB_policy.md" in filenames_b, filenames_b

    assert "tenantA_policy.md" not in filenames_b, filenames_b

    print(f"场景3b ✅ 企业B只见自己文档: {filenames_b}")

    # ======================
    # 场景4：各管理员可操作自己租户文档 → 204
    # ======================

    resp = client.delete(
        f"/api/admin/documents/{doc_a_id}",
        headers=headers_a
    )

    assert resp.status_code == 204, f"场景4a失败: {resp.status_code} {resp.text}"

    print("场景4a ✅ 企业A删除自己文档 → 204")

    resp = client.delete(
        f"/api/admin/documents/{doc_b_id}",
        headers=headers_b
    )

    assert resp.status_code == 204, f"场景4b失败: {resp.status_code} {resp.text}"

    print("场景4b ✅ 企业B删除自己文档 → 204")

    print("租户越权测试全部通过")


if __name__ == "__main__":

    test()
