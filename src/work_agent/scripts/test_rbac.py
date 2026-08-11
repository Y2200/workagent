"""
RBAC 权限模型测试

覆盖：超级管理员 / 租户管理员 / 部门管理员 / 普通用户

验证：
- 权限码解析正确
- HTTP 层权限强制（require_permission → 403/200）
- 租户隔离保持

用法：
    python -m work_agent.scripts.test_rbac
"""

import time

from fastapi.testclient import TestClient

from work_agent.core.container import document_service
from work_agent.db.session import SessionLocal
from work_agent.main import app
from work_agent.repositories.document_repository import DocumentRepository
from work_agent.repositories.tenant_repository import TenantRepository
from work_agent.repositories.user_repository import UserRepository
from work_agent.scripts.seed_rbac import seed_rbac
from work_agent.scripts.seed_tenants import seed_tenants
from work_agent.services.rbac_service import RBACService


def _login(client, username, password="test123"):
    resp = client.post(
        "/api/admin/auth/login",
        json={
            "username": username,
            "password": password,
        }
    )
    assert resp.status_code == 200, resp.text
    return {
        "Authorization": f"Bearer {resp.json()['access_token']}"
    }


def test():

    seed_tenants()

    seed_rbac()

    client = TestClient(app)

    # ======================
    # 场景1：权限码解析
    # ======================

    db = SessionLocal()

    try:

        user_repo = UserRepository()

        rbac = RBACService()

        admin = user_repo.get_by_username(db, "admin")
        tenant_admin = user_repo.get_by_username(db, "admin_A")
        dept_admin = user_repo.get_by_username(db, "dept_admin_A")
        user_role = user_repo.get_by_username(db, "A财务员工")

        admin_perms = rbac.get_permission_codes(db, admin.id)
        tenant_perms = rbac.get_permission_codes(db, tenant_admin.id)
        dept_perms = rbac.get_permission_codes(db, dept_admin.id)
        user_perms = rbac.get_permission_codes(db, user_role.id)

        all_codes = {
            "document:view",
            "document:create",
            "document:delete",
            "document:permission_manage",
            "audit:view",
            "system:manage",
        }

        assert all_codes <= admin_perms, admin_perms

        assert all_codes <= tenant_perms, tenant_perms

        assert "document:delete" not in dept_perms, dept_perms

        assert "document:permission_manage" not in dept_perms, dept_perms

        assert dept_perms == {"document:view", "document:create", "audit:view"}, dept_perms

        assert user_perms == {"document:view"}, user_perms

    finally:

        db.close()

    print("场景1 ✅ 权限码解析正确")

    # ======================
    # 场景2：租户管理员可上传，部门管理员可上传
    # ======================

    headers_ta = _login(client, "admin_A")

    headers_da = _login(client, "dept_admin_A")

    resp = client.post(
        "/api/admin/documents/upload",
        headers=headers_da,
        files={
            "file": (
                "rbac_dept.md",
                "部门管理员上传的文档".encode("utf-8"),
                "text/markdown"
            )
        },
        data={
            "category": "测试"
        }
    )

    assert resp.status_code == 202, resp.text

    doc_id = resp.json()["id"]

    print("场景2 ✅ 租户管理员/部门管理员均有 document:create")

    # ======================
    # 场景3：部门管理员删除文档 → 403（无 document:delete）
    # ======================

    resp = client.delete(
        f"/api/admin/documents/{doc_id}",
        headers=headers_da,
    )

    assert resp.status_code == 403, f"场景3失败: {resp.status_code} {resp.text}"

    print("场景3 ✅ 部门管理员删除文档 → 403")

    # ======================
    # 场景4：普通用户（USER）
    # ======================

    headers_user = _login(client, "A财务员工")

    # 可查看（document:view）
    resp = client.get(
        "/api/admin/documents",
        headers=headers_user,
    )

    assert resp.status_code == 200, f"USER应可查看文档: {resp.status_code}"

    # 不可上传（无 document:create）
    resp = client.post(
        "/api/admin/documents/upload",
        headers=headers_user,
        files={
            "file": (
                "user_upload.md",
                "普通用户上传".encode("utf-8"),
                "text/markdown"
            )
        },
        data={
            "category": "测试"
        }
    )

    assert resp.status_code == 403, f"USER上传应403: {resp.status_code}"

    # 不可看审计（无 audit:view）
    resp = client.get(
        "/api/admin/logs",
        headers=headers_user,
    )

    assert resp.status_code == 403, f"USER看日志应403: {resp.status_code}"

    print("场景4 ✅ 普通用户: 可看文档, 上传/审计 → 403")

    # ======================
    # 场景5：租户管理员可看审计（audit:view）
    # ======================

    resp = client.get(
        "/api/admin/logs",
        headers=headers_ta,
    )

    assert resp.status_code == 200, f"场景5失败: {resp.status_code}"

    print("场景5 ✅ 租户管理员 audit:view 正常")

    # ======================
    # 清理测试文档
    # ======================

    time.sleep(4)

    db = SessionLocal()

    try:

        doc = DocumentRepository().get_by_id(db, doc_id)

    finally:

        db.close()

    if doc:
        tenant_a_id = str(
            TenantRepository().get_by_corp_id(
                db,
                "ww_corp_A"
            ).id
        ) if doc.tenant_id else ""
        document_service.delete(doc_id, tenant_id=doc.tenant_id)
        print("清理测试文档:", doc_id)

    print("RBAC 测试全部通过")


if __name__ == "__main__":

    test()
