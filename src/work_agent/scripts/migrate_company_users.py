"""
单公司模型迁移：存量平台租户用户 → 公司租户

背景：此前企微自动建号默认空租户（平台），新绑定用户落在租户""。
单公司模型下所有用户应归属公司租户（settings.default_tenant_id，默认 "1"）。

规则（幂等）：
- 把 tenant_id == "" 的用户全部改为 default_tenant_id（含历史管理员）
- SUPER_ADMIN 角色不受影响：仍按角色看全量（_tenant_scope）
- 已有租户（非空）的用户不动

用法：
    python -m work_agent.scripts.migrate_company_users
"""

from work_agent.config import settings
from work_agent.db.session import SessionLocal
from work_agent.repositories.user_repository import UserRepository


def migrate_company_users() -> int:

    db = SessionLocal()

    try:

        repo = UserRepository()

        platform_users = repo.list_by_tenant(
            db,
            tenant_id="",
        )

        for user in platform_users:

            user.tenant_id = settings.default_tenant_id

        db.commit()

        return len(platform_users)

    finally:

        db.close()


if __name__ == "__main__":

    moved = migrate_company_users()

    print(f"迁移完成：{moved} 个平台租户用户 → 租户 {settings.default_tenant_id}")
