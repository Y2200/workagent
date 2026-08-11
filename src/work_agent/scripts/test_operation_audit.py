"""
操作审计测试

验证：
- 操作记录生成（登录成功/失败、上传、删除）
- 租户隔离（企业B管理员看不到企业A操作日志）

用法：
    python -m work_agent.scripts.test_operation_audit
"""

from fastapi.testclient import TestClient

from work_agent.db.models import OperationLog
from work_agent.db.session import SessionLocal
from work_agent.main import app
from work_agent.repositories.tenant_repository import TenantRepository
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


def test():

    seed_tenants()

    tenant_a_id = _tenant_id_by_corp("ww_corp_A")

    tenant_b_id = _tenant_id_by_corp("ww_corp_B")

    client = TestClient(app)

    # ======================
    # 企业A管理员：登录失败 + 登录成功 + 上传 + 删除
    # ======================

    resp = client.post(
        "/api/admin/auth/login",
        json={
            "username": "admin_A",
            "password": "wrong_password"
        }
    )

    assert resp.status_code == 401, resp.text

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
        "/api/admin/documents/upload",
        headers=headers_a,
        files={
            "file": (
                "op_audit_a.md",
                "企业A操作审计文档".encode("utf-8"),
                "text/markdown"
            )
        },
        data={
            "category": "测试"
        }
    )

    assert resp.status_code == 202, resp.text

    doc_a_id = resp.json()["id"]

    resp = client.delete(
        f"/api/admin/documents/{doc_a_id}",
        headers=headers_a,
    )

    assert resp.status_code == 204, resp.text

    # ======================
    # 企业A操作日志查询（需等管线完成删除，但操作日志已写入）
    # ======================

    resp = client.get(
        "/api/admin/operations",
        headers=headers_a,
        params={
            "page_size": 50
        }
    )

    assert resp.status_code == 200, resp.text

    ops_a = resp.json()["items"]

    actions_a = [op["action"] for op in ops_a]

    assert "auth.login" in actions_a, actions_a

    # 失败登录无法归属租户，记在默认租户（不会出现在企业A列表）
    assert "auth.login_failed" not in actions_a, actions_a

    assert "document.create" in actions_a, actions_a

    assert "document.delete" in actions_a, actions_a

    print(
        f"场景1 ✅ 企业A操作记录: "
        f"{sorted(set(a for a in actions_a if 'auth' in a or 'document' in a))}"
    )

    # 失败登录记录在默认租户，默认管理员可见
    resp = client.post(
        "/api/admin/auth/login",
        json={
            "username": "admin",
            "password": "admin123"
        }
    )

    assert resp.status_code == 200, resp.text

    headers_default = {
        "Authorization": f"Bearer {resp.json()['access_token']}"
    }

    resp = client.get(
        "/api/admin/operations",
        headers=headers_default,
        params={
            "page_size": 50
        }
    )

    actions_default = [
        op["action"]
        for op in resp.json()["items"]
    ]

    assert "auth.login_failed" in actions_default, actions_default

    print(
        f"场景1b ✅ 登录失败记录: 默认租户可见 auth.login_failed"
    )

    # 文档删除为异步，等待管线完成后再清理验证
    import time
    from work_agent.repositories.document_repository import DocumentRepository
    from work_agent.core.container import document_service
    time.sleep(4)
    db = SessionLocal()
    try:
        doc = DocumentRepository().get_by_id(db, doc_a_id)
    finally:
        db.close()
    if doc:
        document_service.delete(doc_a_id, tenant_id=tenant_a_id)
        print("清理测试文档:", doc_a_id)

    # ======================
    # 租户隔离：企业B管理员看不到企业A操作日志
    # ======================

    resp = client.post(
        "/api/admin/auth/login",
        json={
            "username": "admin_B",
            "password": "test123"
        }
    )

    assert resp.status_code == 200, resp.text

    headers_b = {
        "Authorization": f"Bearer {resp.json()['access_token']}"
    }

    resp = client.get(
        "/api/admin/operations",
        headers=headers_b,
        params={
            "page_size": 50
        }
    )

    assert resp.status_code == 200, resp.text

    ops_b = resp.json()["items"]

    for op in ops_b:
        assert op["tenant_id"] == tenant_b_id, (
            f"场景2失败: 企业B看到企业A操作 tenant_id={op['tenant_id']}"
        )

    # 企业A的登录/上传操作不应出现在企业B
    assert all(
        op["tenant_id"] != tenant_a_id
        for op in ops_b
    ), "场景2失败: 企业B操作列表混入企业A"

    print(
        f"场景2 ✅ 租户隔离: 企业B操作日志{len(ops_b)}条全为tenant {tenant_b_id}"
    )

    # 清理企业A/B 测试产生的操作日志
    db = SessionLocal()
    try:
        db.query(OperationLog).filter(
            OperationLog.tenant_id.in_([tenant_a_id, tenant_b_id]),
            OperationLog.action.in_([
                "document.create",
                "document.delete",
            ]),
        ).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()

    print("操作审计测试全部通过")


if __name__ == "__main__":

    test()
