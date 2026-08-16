"""
迁移：agent_logs 智能体审计字段

用法：
    python -m work_agent.scripts.migrate_agent_intelligence
"""

from sqlalchemy import text

from work_agent.db.session import engine


_ALTER_STATEMENTS = [
    "ALTER TABLE agent_logs ADD COLUMN IF NOT EXISTS agent_version VARCHAR(32) DEFAULT ''",
    "ALTER TABLE agent_logs ADD COLUMN IF NOT EXISTS model_name VARCHAR(64) DEFAULT ''",
    "ALTER TABLE agent_logs ADD COLUMN IF NOT EXISTS prompt_version VARCHAR(32) DEFAULT ''",
    "ALTER TABLE agent_logs ADD COLUMN IF NOT EXISTS intent_confidence FLOAT DEFAULT 0",
    "ALTER TABLE agent_logs ADD COLUMN IF NOT EXISTS tools_called JSON",
    "ALTER TABLE agent_logs ADD COLUMN IF NOT EXISTS confirmed BOOLEAN",
]


def migrate():

    with engine.begin() as conn:

        for statement in _ALTER_STATEMENTS:

            conn.execute(
                text(statement)
            )

    print("迁移完成：agent_logs 智能体审计字段已补充")


if __name__ == "__main__":

    migrate()
