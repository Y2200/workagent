"""
迁移：conversation_messages 会话消息表（Enterprise Agent 会话记忆）

用法：
    python -m work_agent.scripts.migrate_conversation_messages
"""

from work_agent.db.base import Base
from work_agent.db.models.conversation_message import ConversationMessage
from work_agent.db.session import engine


def migrate():

    Base.metadata.create_all(
        bind=engine,
        tables=[
            ConversationMessage.__table__,
        ],
    )

    print("迁移完成：conversation_messages 已就绪")


if __name__ == "__main__":

    migrate()
