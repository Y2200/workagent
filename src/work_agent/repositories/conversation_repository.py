from datetime import datetime

from sqlalchemy.orm import Session

from work_agent.db.models import Conversation


class ConversationRepository:

    """
    会话数据访问
    """

    def get_active(
            self,
            db: Session,
            *,
            tenant_id: str,
            user_id: int,
            channel: str
    ):

        return (
            db.query(Conversation)
            .filter(
                Conversation.tenant_id == tenant_id,
                Conversation.user_id == user_id,
                Conversation.channel == channel,
                Conversation.status == "active",
            )
            .order_by(Conversation.id.desc())
            .first()
        )


    def create(
            self,
            db: Session,
            *,
            tenant_id: str,
            user_id: int,
            channel: str
    ) -> Conversation:

        conversation = Conversation(
            tenant_id=tenant_id,
            user_id=user_id,
            channel=channel,
            status="active",
            message_count=0,
        )

        db.add(conversation)

        db.commit()

        db.refresh(conversation)

        return conversation


    def touch(
            self,
            db: Session,
            conversation_id: int
    ) -> None:

        """
        记录一次活动：消息数+1，更新最后活跃时间
        """

        conversation = db.get(
            Conversation,
            conversation_id
        )

        if not conversation:
            return

        conversation.message_count += 1

        conversation.last_activity_at = datetime.now()

        db.add(conversation)

        db.commit()
