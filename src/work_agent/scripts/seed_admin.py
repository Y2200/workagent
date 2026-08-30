"""
创建初始管理员

用法：
    python -m work_agent.scripts.seed_admin
"""

from work_agent.config import settings
from work_agent.db.session import SessionLocal
from work_agent.repositories.user_repository import UserRepository
from work_agent.services.auth_service import AuthService


def seed_admin():

    db = SessionLocal()

    try:

        repository = UserRepository()

        if repository.get_by_username(
                db,
                settings.admin_username
        ):

            print(
                f"管理员 {settings.admin_username} 已存在"
            )

            return

        repository.create(
            db,
            username=settings.admin_username,
            password_hash=AuthService.hash_password(
                settings.admin_password
            ),
            department="管理层",
            role="管理员",
            # 单公司模型：管理员归属公司租户（default_tenant_id）。
            # 可见性不受影响：SUPER_ADMIN 角色 → _tenant_scope 平台全量。
            # 不用 settings.tenant_id——避免测试/部署配了 TENANT_ID 时管理员跟着漂移。
            tenant_id=settings.default_tenant_id
        )

        print(
            f"管理员 {settings.admin_username} 创建成功"
        )

    finally:

        db.close()


if __name__ == "__main__":

    seed_admin()
