"""
RBAC 角色权限初始化

用法：
    python -m work_agent.scripts.seed_rbac
"""

from work_agent.db.session import SessionLocal
from work_agent.repositories.user_repository import UserRepository
from work_agent.services.auth_service import AuthService
from work_agent.services.rbac_service import RBACService


PERMISSIONS = [
    ("document:view", "查看文档", "查看知识库文档"),
    ("document:create", "创建文档", "上传文档"),
    ("document:delete", "删除文档", "删除文档及其向量"),
    ("document:permission_manage", "权限管理", "修改文档访问权限"),
    ("audit:view", "查看审计", "查看问答与操作审计"),
    ("system:manage", "系统管理", "系统级运维操作（归档等）"),
    ("user:manage", "用户管理", "绑定/解绑企业微信账号"),
]

# 角色 → 权限码
ROLES = {
    "SUPER_ADMIN": {
        "name": "超级管理员",
        "permissions": [
            "document:view",
            "document:create",
            "document:delete",
            "document:permission_manage",
            "audit:view",
            "system:manage",
            "user:manage",
        ],
    },
    "TENANT_ADMIN": {
        "name": "租户管理员",
        "permissions": [
            "document:view",
            "document:create",
            "document:delete",
            "document:permission_manage",
            "audit:view",
            "system:manage",
            "user:manage",
        ],
    },
    "DEPARTMENT_ADMIN": {
        "name": "部门管理员",
        "permissions": [
            "document:view",
            "document:create",
            "audit:view",
        ],
    },
    "USER": {
        "name": "普通用户",
        "permissions": [
            "document:view",
        ],
    },
}

# 用户 → 角色（按 username）
USER_ROLES = {
    "admin": "SUPER_ADMIN",
    "admin_A": "TENANT_ADMIN",
    "admin_B": "TENANT_ADMIN",
    "员工A": "USER",
    "A财务员工": "USER",
    "A研发员工": "USER",
    "B市场员工": "USER",
    "dept_admin_A": "DEPARTMENT_ADMIN",
}


def _ensure_dept_admin(db) -> None:

    """
    创建部门管理员测试用户
    """

    user_repo = UserRepository()

    if user_repo.get_by_username(
            db,
            "dept_admin_A"
    ):
        return

    user_repo.create(
        db,
        username="dept_admin_A",
        password_hash=AuthService.hash_password(
            "test123"
        ),
        department="研发部",
        role="管理员",
        wechat_user_id="wx_A_dept_admin",
        tenant_id="1",
    )

    print("创建部门管理员: dept_admin_A")


def seed_rbac():

    service = RBACService()

    db = SessionLocal()

    try:

        user_repo = UserRepository()

        # ======================
        # 权限点
        # ======================

        for code, name, description in PERMISSIONS:

            service.create_permission(
                db,
                code=code,
                name=name,
                description=description,
            )

        # ======================
        # 角色 + 权限映射
        # ======================

        for role_code, config in ROLES.items():

            role = service.create_role(
                db,
                code=role_code,
                name=config["name"],
                description=config["name"],
            )

            for perm_code in config["permissions"]:

                permission = service.get_permission_by_code(
                    db,
                    perm_code
                )

                if permission:

                    service.assign_permission(
                        db,
                        role.id,
                        permission.id,
                    )

        # ======================
        # 部门管理员测试用户
        # ======================

        _ensure_dept_admin(db)

        # ======================
        # 用户 → 角色
        # ======================

        for username, role_code in USER_ROLES.items():

            user = user_repo.get_by_username(
                db,
                username
            )

            if user:

                service.assign_role(
                    db,
                    user.id,
                    role_code,
                )

        print("RBAC 初始化完成")

    finally:

        db.close()


if __name__ == "__main__":

    seed_rbac()
