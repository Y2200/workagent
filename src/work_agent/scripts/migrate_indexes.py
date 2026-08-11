"""
迁移：补齐生产级索引

- 时间字段 created_at 索引（日志高频时间过滤）
- 组合索引：
  - agent_logs (tenant_id, created_at)
  - operation_logs (tenant_id, created_at)
  - documents (tenant_id, status)
- roles.tenant_id 索引
- document_permission.user_id 索引

用法：
    python -m work_agent.scripts.migrate_indexes
"""

from sqlalchemy import text

from work_agent.db.session import engine


_INDEX_STATEMENTS = [
    # agent_logs
    "CREATE INDEX IF NOT EXISTS ix_agent_logs_created_at ON agent_logs (created_at)",
    "CREATE INDEX IF NOT EXISTS ix_agent_logs_tenant_created ON agent_logs (tenant_id, created_at)",
    # operation_logs
    "CREATE INDEX IF NOT EXISTS ix_operation_logs_created_at ON operation_logs (created_at)",
    "CREATE INDEX IF NOT EXISTS ix_operation_logs_tenant_created ON operation_logs (tenant_id, created_at)",
    # documents
    "CREATE INDEX IF NOT EXISTS ix_documents_tenant_status ON documents (tenant_id, status)",
    # roles
    "CREATE INDEX IF NOT EXISTS ix_roles_tenant_id ON roles (tenant_id)",
    # document_permission
    "CREATE INDEX IF NOT EXISTS ix_document_permission_user_id ON document_permission (user_id)",
]


def migrate():

    with engine.begin() as conn:

        for statement in _INDEX_STATEMENTS:

            conn.execute(
                text(statement)
            )

    print("迁移完成：生产级索引已补齐")


if __name__ == "__main__":

    migrate()
