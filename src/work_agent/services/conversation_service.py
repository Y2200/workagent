from work_agent.db.session import SessionLocal
from work_agent.repositories.conversation_repository import ConversationRepository


class ConversationService:

    """
    会话服务

    按 (tenant_id, user_id, channel) 获取或创建会话
    支持会话连续性与审计
    """

    def __init__(
            self,
            repository: ConversationRepository | None = None
    ):

        self.repository = repository or ConversationRepository()


    def get_or_create(
            self,
            *,
            tenant_id: str,
            user_id: int,
            channel: str = "wechat"
    ) -> int:

        """
        获取或创建会话，返回 conversation_id
        """

        db = SessionLocal()

        try:

            conversation = self.repository.get_active(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
                channel=channel,
            )

            if conversation is None:

                conversation = self.repository.create(
                    db,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    channel=channel,
                )

            return conversation.id

        finally:

            db.close()


    def touch(
            self,
            conversation_id: int
    ) -> None:

        """
        记录一次会话活动
        """

        db = SessionLocal()

        try:

            self.repository.touch(
                db,
                conversation_id,
            )

        finally:

            db.close()


# 全局单例
conversation_service = ConversationService()
