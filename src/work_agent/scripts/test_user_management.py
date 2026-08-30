"""
用户管理增强测试套件（A/B/C：Web 新建/编辑 + real_name + 企微绑定并发加固）

Part 1  迁移幂等 + real_name 回填 + 部分唯一索引存在
Part 2  POST 创建（SUPER_ADMIN）：用户 + RBAC 角色 + 密码可登录 + real_name
Part 3  创建校验：username 重复 409 / wechat 冲突 409 / 短密码 400
Part 4  租户/角色越权：TENANT_ADMIN 跨租户 403 / 越权授角色 403 / SUPER_ADMIN 可赋任意
Part 5  PUT 编辑：real_name/dept/role 更新 + 跨租户 403
Part 6  find-or-create：同 userid 两次 → 仅 1 行、第二次返回已存在者
Part 7  唯一索引兜底：直插同 wechat_user_id → IntegrityError
Part 8  bind 冲突回归 409

用法：
    python -m work_agent.scripts.test_user_management
"""

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from work_agent.config import settings
from work_agent.db.models import User
from work_agent.db.session import SessionLocal
from work_agent.main import app
from work_agent.repositories.user_repository import UserRepository
from work_agent.scripts.migrate_user_profile import migrate as migrate_user_profile
from work_agent.scripts.seed_admin import seed_admin
from work_agent.scripts.seed_rbac import seed_rbac
from work_agent.scripts.seed_tenants import seed_tenants


_TEST_USERS = [
    "测试新建用户",
    "测试新建冲突",
    "测试本租户用户",
    "测试超级管理员",
    "测试编辑用户",
    "wx_find_or_create_test",
    "wx_unique_index",
]


def _setup():

    seed_admin()

    seed_tenants()

    seed_rbac()

    migrate_user_profile()

    _cleanup()


def _cleanup():

    db = SessionLocal()

    try:

        for name in _TEST_USERS:

            user = UserRepository().get_by_username(
                db,
                name,
            )

            if user:

                db.delete(user)

        db.commit()

    finally:

        db.close()


def _login(
        client,
        username,
        password="test123"
):

    resp = client.post(
        "/api/admin/auth/login",
        json={
            "username": username,
            "password": password,
        },
    )

    assert resp.status_code == 200, resp.text

    return {
        "Authorization": f"Bearer {resp.json()['access_token']}"
    }


def _login_admin(client):

    return _login(
        client,
        settings.admin_username or "admin",
        settings.admin_password,
    )


def _user(username):

    db = SessionLocal()

    try:

        return UserRepository().get_by_username(
            db,
            username,
        )

    finally:

        db.close()


# ======================
# Part 1 迁移
# ======================

def test_migration():

    # 幂等：跑两遍不报错
    migrate_user_profile()

    migrate_user_profile()

    db = SessionLocal()

    try:

        # 存量用户 real_name 已回填 = username
        admin = _user(settings.admin_username or "admin")

        assert admin and admin.real_name, "real_name 应已回填"

        # 部分唯一索引存在
        exists = db.execute(
            text(
                "SELECT 1 FROM pg_indexes "
                "WHERE indexname = 'ix_users_wechat_user_id_unique'"
            )
        ).scalar()

        assert exists, "部分唯一索引应存在"

    finally:

        db.close()

    print("Part 1 ✅ 迁移幂等 + real_name 回填 + 部分唯一索引存在")


# ======================
# Part 2 POST 创建
# ======================

def test_create_super_admin():

    client = TestClient(app)

    headers = _login_admin(client)

    resp = client.post(
        "/api/admin/users",
        headers=headers,
        json={
            "username": "测试新建用户",
            "real_name": "张三",
            "department": "研发部",
            "role": "DEPARTMENT_ADMIN",
            "tenant_id": "1",
        },
    )

    assert resp.status_code == 201, resp.text

    body = resp.json()

    assert body["real_name"] == "张三", body

    assert "DEPARTMENT_ADMIN" in body["roles"], body

    assert body["tenant_id"] == "1", body

    # 单公司模型：员工无 Web 密码 → 不能密码登录（只能企微）
    token_resp = client.post(
        "/api/admin/auth/login",
        json={
            "username": "测试新建用户",
            "password": "test123",
        },
    )

    assert token_resp.status_code == 401, token_resp.text

    print("Part 2 ✅ POST 创建（SUPER_ADMIN）：用户 + 角色 + 租户1 + 无密码不可登录")


# ======================
# Part 3 创建校验
# ======================

def test_create_validation():

    client = TestClient(app)

    headers = _login_admin(client)

    # ① username 重复 → 409
    resp = client.post(
        "/api/admin/users",
        headers=headers,
        json={
            "username": "测试新建用户",
        },
    )

    assert resp.status_code == 409, resp.text

    # ② wechat 冲突 → 409（先建一个绑定 wx_dup 的）
    client.post(
        "/api/admin/users",
        headers=headers,
        json={
            "username": "测试新建冲突",
            "wechat_user_id": "wx_dup",
        },
    )

    resp = client.post(
        "/api/admin/users",
        headers=headers,
        json={
            "username": "测试新建冲突2",
            "wechat_user_id": "wx_dup",
        },
    )

    assert resp.status_code == 409, resp.text

    # ③ 用户名留空 → 自动生成（默认租户1）
    resp = client.post(
        "/api/admin/users",
        headers=headers,
        json={
            "real_name": "自动生成用户名",
            "department": "财务部",
        },
    )

    assert resp.status_code == 201, resp.text

    body = resp.json()

    assert body["username"], "应自动生成用户名"
    assert body["tenant_id"] == "1", body

    print("Part 3 ✅ 创建校验（username 重复 409 / wechat 冲突 409 / 留空自动生成+默认租户1）")


# ======================
# Part 4 租户/角色越权
# ======================

def test_tenant_role_permission():

    client = TestClient(app)

    admin_a = _user("admin_A")

    assert admin_a and admin_a.tenant_id, "需要 admin_A 租户管理员"

    other_tenant = (
        "2"
        if admin_a.tenant_id != "2"
        else "3"
    )

    headers_ta = _login(client, "admin_A")

    # ① 租户管理员跨租户创建 → 403
    resp = client.post(
        "/api/admin/users",
        headers=headers_ta,
        json={
            "username": "测试越权用户",
            "password": "test123",
            "tenant_id": other_tenant,
        },
    )

    assert resp.status_code == 403, resp.text

    # ② 租户管理员越权授 TENANT_ADMIN → 403
    resp = client.post(
        "/api/admin/users",
        headers=headers_ta,
        json={
            "username": "测试越权角色",
            "password": "test123",
            "role": "TENANT_ADMIN",
        },
    )

    assert resp.status_code == 403, resp.text

    # ③ 租户管理员本租户建普通用户 → 201，且租户被强制为本租户
    resp = client.post(
        "/api/admin/users",
        headers=headers_ta,
        json={
            "username": "测试本租户用户",
            "password": "test123",
            "role": "USER",
            "tenant_id": "",
        },
    )

    assert resp.status_code == 201, resp.text

    assert resp.json()["tenant_id"] == admin_a.tenant_id, resp.json()

    # ④ SUPER_ADMIN 可赋任意（SUPER_ADMIN）
    headers_admin = _login_admin(client)

    resp = client.post(
        "/api/admin/users",
        headers=headers_admin,
        json={
            "username": "测试超级管理员",
            "password": "test123",
            "role": "SUPER_ADMIN",
        },
    )

    assert resp.status_code == 201, resp.text

    assert "SUPER_ADMIN" in resp.json()["roles"], resp.json()

    print("Part 4 ✅ 租户/角色越权（跨租户 403 / 越权授角色 403 / 强制本租户 / SUPER_ADMIN 可赋任意）")


# ======================
# Part 5 PUT 编辑
# ======================

def test_update_user():

    client = TestClient(app)

    headers_admin = _login_admin(client)

    user = _user("测试编辑用户")

    if not user:

        resp = client.post(
            "/api/admin/users",
            headers=headers_admin,
            json={
                "username": "测试编辑用户",
                "password": "test123",
            },
        )

        assert resp.status_code == 201, resp.text

        user = _user("测试编辑用户")

    user_id = user.id

    resp = client.put(
        f"/api/admin/users/{user_id}",
        headers=headers_admin,
        json={
            "real_name": "李四",
            "department": "财务部",
            "role": "DEPARTMENT_ADMIN",
        },
    )

    assert resp.status_code == 200, resp.text

    body = resp.json()

    assert body["real_name"] == "李四", body

    assert body["department"] == "财务部", body

    assert "DEPARTMENT_ADMIN" in body["roles"], body

    # 跨租户编辑 → 403（admin_B 是另一租户租户管理员）
    headers_other = _login(client, "admin_B")

    resp = client.put(
        f"/api/admin/users/{user_id}",
        headers=headers_other,
        json={
            "real_name": "恶意改名",
        },
    )

    assert resp.status_code == 403, resp.text

    print("Part 5 ✅ PUT 编辑（real_name/dept/role 更新 + 跨租户 403）")


# ======================
# Part 6 find-or-create
# ======================

def test_find_or_create():

    import work_agent.wechat.service as ws

    class FakeClient:

        def get_user_info(
                self,
                user_id
        ):

            return {
                "errcode": 0,
                "name": "自动建号用户",
                "userid": user_id,
            }

    # _auto_create_user 用的是 service 模块导入时绑定的 wecom_client
    ws.wecom_client = FakeClient()

    uid = "wx_find_or_create_test"

    # 只清理本用例的用户，不误删其他 Part 需要的用户
    # 注意：自动建号 username = wx_{uid}，须按 wechat_user_id 定位
    db = SessionLocal()

    try:

        existing = UserRepository().get_by_wechat_user_id(
            db,
            uid,
        )

        if existing:

            db.delete(existing)

            db.commit()

    finally:

        db.close()

    u1 = ws._auto_create_user(uid)

    u2 = ws._auto_create_user(uid)

    assert u1 is not None

    assert u2 is not None

    assert u1.id == u2.id, "两次建号应返回同一用户"

    assert u1.real_name == "自动建号用户", u1.real_name

    # 单公司模型：自动建号落公司租户（default_tenant_id）
    assert u1.tenant_id == settings.default_tenant_id, u1.tenant_id

    db = SessionLocal()

    try:

        count = (
            db.query(User)
            .filter(User.wechat_user_id == uid)
            .count()
        )

    finally:

        db.close()

    assert count == 1, f"应只有 1 个用户，实际 {count}"

    print("Part 6 ✅ find-or-create（同 userid 两次 → 仅 1 行、返回已存在者）")


# ======================
# Part 7 唯一索引兜底
# ======================

def test_unique_index():

    db = SessionLocal()

    try:

        UserRepository().create(
            db,
            username="wx_unique_index",
            password_hash="x",
            real_name="索引甲",
            wechat_user_id="wx_unique_index",
            tenant_id="1",
        )

        try:

            UserRepository().create(
                db,
                username="wx_unique_index_2",
                password_hash="x",
                real_name="索引乙",
                wechat_user_id="wx_unique_index",
                tenant_id="1",
            )

            raise AssertionError("同 wechat_user_id 直插应触发 IntegrityError")

        except IntegrityError:

            db.rollback()

    finally:

        db.close()

    print("Part 7 ✅ 唯一索引兜底（DB 层拒绝重复 wechat_user_id）")


# ======================
# Part 8 bind 冲突回归
# ======================

def test_bind_conflict():

    client = TestClient(app)

    headers = _login_admin(client)

    u1 = _user("测试新建用户")

    u2 = _user("测试编辑用户")

    # 给 u1 绑定 wx_bind_a
    resp = client.put(
        f"/api/admin/users/{u1.id}/wechat",
        headers=headers,
        json={"wechat_user_id": "wx_bind_a"},
    )

    assert resp.status_code == 200, resp.text

    # 再给 u2 绑同一 wx → 409
    resp = client.put(
        f"/api/admin/users/{u2.id}/wechat",
        headers=headers,
        json={"wechat_user_id": "wx_bind_a"},
    )

    assert resp.status_code == 409, resp.text

    print("Part 8 ✅ bind 冲突回归 409")


def test_delete_user():

    """Part 9：删除用户（解绑后残留清理）"""

    from work_agent.core.container import task_service
    from work_agent.db.session import SessionLocal
    from work_agent.repositories.user_repository import UserRepository

    client = TestClient(app)

    headers = _login_admin(client)

    # ① 删自己 → 400
    me = _user(settings.admin_username)
    resp = client.delete(
        f"/api/admin/users/{me.id}",
        headers=headers,
    )
    assert resp.status_code == 400, resp.text

    # ② 无任务用户 → 204 删除成功
    resp = client.post(
        "/api/admin/users",
        headers=headers,
        json={
            "real_name": "待删除用户",
            "department": "研发部",
            "tenant_id": "1",
        },
    )
    assert resp.status_code == 201, resp.text
    del_user = resp.json()

    resp = client.delete(
        f"/api/admin/users/{del_user['id']}",
        headers=headers,
    )
    assert resp.status_code == 204, resp.text

    db = SessionLocal()
    try:
        assert UserRepository().get_by_id(db, del_user["id"]) is None, "应已删除"
    finally:
        db.close()

    # ③ 有任务用户 → 409（保护数据完整性）
    resp = client.post(
        "/api/admin/users",
        headers=headers,
        json={
            "real_name": "有任务用户",
            "department": "研发部",
            "tenant_id": "1",
        },
    )
    assert resp.status_code == 201, resp.text
    task_user = resp.json()

    task_service.create_task(
        creator_tenant_id="1",
        title="删除守卫测试任务",
        creator_id=me.id,
        employee_id=task_user["id"],
        department="研发部",
    )

    resp = client.delete(
        f"/api/admin/users/{task_user['id']}",
        headers=headers,
    )
    assert resp.status_code == 409, resp.text

    print("Part 9 ✅ 删除用户（删自己 400 / 无任务 204 / 有任务 409）")


def test():

    _setup()

    test_migration()

    test_create_super_admin()

    test_create_validation()

    test_tenant_role_permission()

    test_update_user()

    test_find_or_create()

    test_unique_index()

    test_bind_conflict()

    test_delete_user()


if __name__ == "__main__":

    test()
