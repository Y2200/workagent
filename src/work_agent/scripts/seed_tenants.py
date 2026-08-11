"""
创建测试租户与员工

用法：
    python -m work_agent.scripts.seed_tenants

包含：
- 企业A / 企业B 两个租户
- 员工A（单租户""，供企业微信闭环）
- 企业A财务员工、企业A研发员工、企业B市场员工（供权限测试）
"""

from work_agent.db.session import SessionLocal
from work_agent.repositories.tenant_repository import TenantRepository
from work_agent.repositories.user_repository import UserRepository
from work_agent.services.auth_service import AuthService


def seed_tenants():

    db = SessionLocal()

    try:

        tenant_repo = TenantRepository()

        user_repo = UserRepository()

        # ======================
        # 租户
        # ======================

        tenant_a = tenant_repo.get_by_corp_id(
            db,
            "ww_corp_A"
        )

        if not tenant_a:

            tenant_a = tenant_repo.create(
                db,
                name="企业A",
                corp_id="ww_corp_A"
            )

            print(f"创建租户: {tenant_a.name} (id={tenant_a.id})")

        tenant_b = tenant_repo.get_by_corp_id(
            db,
            "ww_corp_B"
        )

        if not tenant_b:

            tenant_b = tenant_repo.create(
                db,
                name="企业B",
                corp_id="ww_corp_B"
            )

            print(f"创建租户: {tenant_b.name} (id={tenant_b.id})")

        tenant_a_id = str(tenant_a.id)

        tenant_b_id = str(tenant_b.id)

        # ======================
        # 员工
        # ======================

        employees = [
            # 企业微信闭环员工（默认单租户）
            ("员工A", "员工A", "", "财务部", "员工"),
            # 权限测试场景员工
            ("A财务员工", "wx_A_finance", tenant_a_id, "财务部", "员工"),
            ("A研发员工", "wx_A_dev", tenant_a_id, "研发部", "员工"),
            ("B市场员工", "wx_B_market", tenant_b_id, "市场部", "员工"),
            # 租户管理员（越权测试）
            ("admin_A", "wx_A_admin", tenant_a_id, "管理层", "管理员"),
            ("admin_B", "wx_B_admin", tenant_b_id, "管理层", "管理员"),
        ]

        for username, wechat_id, tenant_id, department, role in employees:

            if user_repo.get_by_wechat_user_id(
                    db,
                    wechat_id
            ):
                continue

            user_repo.create(
                db,
                username=username,
                password_hash=AuthService.hash_password(
                    "test123"
                ),
                department=department,
                role=role,
                wechat_user_id=wechat_id,
                tenant_id=tenant_id
            )

            print(
                f"创建员工: {username} "
                f"(tenant={tenant_id}, dept={department}, role={role})"
            )

    finally:

        db.close()

    print("租户与员工初始化完成")


if __name__ == "__main__":

    seed_tenants()
