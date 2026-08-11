"""
初始化数据库表

用法：
    python -m work_agent.scripts.init_db
"""

from work_agent.db.base import Base
from work_agent.db.session import engine


# 触发所有模型注册到 Base.metadata
from work_agent.db import models  # noqa: E402,F401


def init_db():

    """
    创建所有数据表
    """

    Base.metadata.create_all(
        bind=engine
    )

    print("数据库表创建完成")


if __name__ == "__main__":

    init_db()
