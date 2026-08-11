"""
迁移：agent_logs 审计日志表补充字段

不破坏已有数据，使用 ALTER TABLE ADD COLUMN IF NOT EXISTS

用法：
    python -m work_agent.scripts.migrate_agent_logs
"""

from sqlalchemy import text

from work_agent.db.session import engine


_ALTER_STATEMENTS = [
    "ALTER TABLE agent_logs ADD COLUMN IF NOT EXISTS request_id VARCHAR(64)",
    "ALTER TABLE agent_logs ADD COLUMN IF NOT EXISTS channel VARCHAR(16) DEFAULT 'wechat'",
    "ALTER TABLE agent_logs ADD COLUMN IF NOT EXISTS department VARCHAR(64) DEFAULT ''",
    "ALTER TABLE agent_logs ADD COLUMN IF NOT EXISTS role VARCHAR(32) DEFAULT ''",
    "ALTER TABLE agent_logs ADD COLUMN IF NOT EXISTS intent VARCHAR(64) DEFAULT ''",
    "ALTER TABLE agent_logs ADD COLUMN IF NOT EXISTS status VARCHAR(32) DEFAULT 'processing'",
    "ALTER TABLE agent_logs ADD COLUMN IF NOT EXISTS error_type VARCHAR(64)",
    "ALTER TABLE agent_logs ADD COLUMN IF NOT EXISTS error_message TEXT",
    "ALTER TABLE agent_logs ADD COLUMN IF NOT EXISTS retrieval_documents JSON",
    "ALTER TABLE agent_logs ADD COLUMN IF NOT EXISTS latency_ms INTEGER DEFAULT 0",
    "ALTER TABLE agent_logs ADD COLUMN IF NOT EXISTS token_usage INTEGER DEFAULT 0",
    "ALTER TABLE agent_logs ADD COLUMN IF NOT EXISTS archived_at TIMESTAMP",
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_agent_logs_request_id ON agent_logs (request_id)",
    "CREATE INDEX IF NOT EXISTS ix_agent_logs_archived_at ON agent_logs (archived_at)",
]


def migrate():

    with engine.begin() as conn:

        for statement in _ALTER_STATEMENTS:

            conn.execute(
                text(statement)
            )

    print("迁移完成：agent_logs 审计字段已补充")


if __name__ == "__main__":

    migrate()
