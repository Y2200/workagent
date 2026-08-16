"""
迁移：任务督导模块建表 + 租户数据修复

1. create_all 建表（幂等）
2. 历史数据修复：tenant_id 为空的任务，回填为负责人(employee)的租户
3. 校验：剩余空租户任务必须为 0
4. 加 CHECK 约束：tasks.tenant_id 不允许空字符串

用法：
    python -m work_agent.scripts.migrate_tasks
"""

from sqlalchemy import text

from work_agent.db.base import Base
from work_agent.db.models.task import (
    Task,
    TaskNotification,
    TaskPendingCreate,
    TaskPendingUpdate,
    TaskUpdate,
)
from work_agent.db.session import engine


def migrate():

    # 1) 建表（幂等，已存在自动跳过）
    Base.metadata.create_all(
        bind=engine,
        tables=[
            Task.__table__,
            TaskUpdate.__table__,
            TaskPendingUpdate.__table__,
            TaskPendingCreate.__table__,
            TaskNotification.__table__,
        ],
    )

    with engine.begin() as conn:

        # 2) 回填空租户任务：取负责人(employee)的租户
        conn.execute(
            text(
                """
                UPDATE tasks
                SET tenant_id = u.tenant_id
                FROM users u
                WHERE u.id = tasks.employee_id
                  AND tasks.tenant_id = ''
                  AND u.tenant_id <> ''
                """
            )
        )

        # 3) 校验剩余空租户任务
        remaining = conn.execute(
            text(
                "SELECT count(*) FROM tasks WHERE tenant_id = ''"
            )
        ).scalar()

        print(
            f"历史空租户任务回填完成，剩余空租户任务: {remaining}"
        )

        # 4) 约束：tenant_id NOT NULL + 不允许空字符串
        conn.execute(
            text(
                "ALTER TABLE tasks ALTER COLUMN tenant_id SET NOT NULL"
            )
        )

        has_constraint = conn.execute(
            text(
                "SELECT 1 FROM pg_constraint "
                "WHERE conname = 'chk_tasks_tenant_id_not_empty'"
            )
        ).scalar()

        if remaining == 0 and not has_constraint:

            conn.execute(
                text(
                    """
                    ALTER TABLE tasks
                    ADD CONSTRAINT chk_tasks_tenant_id_not_empty
                    CHECK (tenant_id <> '')
                    """
                )
            )

            print("已添加约束：tasks.tenant_id 不允许空字符串")

        elif has_constraint:

            print("约束已存在，跳过")

        else:

            print(
                f"⚠️ 仍有 {remaining} 条任务 tenant_id 为空（负责人亦无租户），"
                "请人工处理后再重跑本脚本以添加 CHECK 约束"
            )

    print(
        "迁移完成：tasks / task_updates / task_pending_updates / "
        "task_notifications 已就绪"
    )


if __name__ == "__main__":

    migrate()
