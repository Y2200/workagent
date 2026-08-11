"""
迁移：新增 tenants 租户表

用法：
    python -m work_agent.scripts.migrate_tenant
"""

from work_agent.db.base import Base
from work_agent.db.session import engine


# 触发所有模型注册到 Base.metadata
from work_agent.db import models  # noqa: E402,F401


def migrate():

    """
    create_all 只创建缺失的表，幂等
    """

    Base.metadata.create_all(
        bind=engine
    )

    print("迁移完成：tenants 表已创建（如不存在）")


if __name__ == "__main__":

    migrate()
