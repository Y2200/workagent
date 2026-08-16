"""
迁移：conversation_messages 会话消息表（Enterprise Agent 会话记忆）

**显式 IF NOT EXISTS SQL**（不用 Base.metadata.create_all）：
- create_all 的 checkfirst 只检查「表」，不检查索引；
  表存在但索引残留（孤儿索引）时会尝试重建索引 → DuplicateTable
- 这里每步 IF NOT EXISTS，表/索引存在即跳过，幂等且健壮

用法：
    python -m work_agent.scripts.migrate_conversation_messages
"""

from sqlalchemy import text

from work_agent.db.session import engine


_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS conversation_messages (
    id BIGSERIAL PRIMARY KEY,
    conversation_id BIGINT NOT NULL,
    role VARCHAR(16) DEFAULT 'user',
    scope VARCHAR(16) DEFAULT 'chat',
    content TEXT NOT NULL,
    tool_name VARCHAR(64),
    extra JSON,
    tenant_id VARCHAR(64) DEFAULT '',
    user_id BIGINT,
    created_at TIMESTAMP DEFAULT now()
)
"""

_CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS "
    "ix_conversation_messages_conversation_id "
    "ON conversation_messages (conversation_id)",

    "CREATE INDEX IF NOT EXISTS "
    "ix_conversation_messages_conversation_scope "
    "ON conversation_messages (conversation_id, scope)",
]


def migrate():

    with engine.begin() as conn:

        conn.execute(
            text(_CREATE_TABLE)
        )

        for ddl in _CREATE_INDEXES:

            conn.execute(
                text(ddl)
            )

    print("迁移完成：conversation_messages 已就绪")


if __name__ == "__main__":

    migrate()
