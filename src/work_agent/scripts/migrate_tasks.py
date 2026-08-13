"""
迁移：任务督导模块建表（tasks / task_updates / task_pending_updates）

create_all 幂等：已存在表自动跳过，不破坏数据

用法：
    python -m work_agent.scripts.migrate_tasks
"""

from work_agent.db.base import Base
from work_agent.db.models.task import (
    Task,
    TaskPendingUpdate,
    TaskUpdate,
)
from work_agent.db.session import engine


def migrate():

    Base.metadata.create_all(
        bind=engine,
        tables=[
            Task.__table__,
            TaskUpdate.__table__,
            TaskPendingUpdate.__table__,
        ],
    )

    print(
        "迁移完成：tasks / task_updates / task_pending_updates 已就绪"
    )


if __name__ == "__main__":

    migrate()
