from datetime import datetime

from sqlalchemy.orm import Session

from work_agent.db.models import Conversation, ConversationMessage


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

    # ======================
    # 会话消息（Enterprise Agent 记忆，Phase 1）
    # ======================

    def append_message(
            self,
            db: Session,
            *,
            conversation_id: int,
            role: str,
            content: str,
            scope: str = "chat",
            tenant_id: str = "",
            user_id: int | None = None,
            tool_name: str | None = None,
            extra: dict | None = None
    ) -> ConversationMessage:

        """
        追加一条会话消息（保存原始字段，不存 BaseMessage）
        """

        message = ConversationMessage(
            conversation_id=int(conversation_id),
            role=role,
            scope=scope,
            content=content,
            tool_name=tool_name,
            extra=extra,
            tenant_id=tenant_id,
            user_id=user_id,
        )

        db.add(message)

        db.commit()

        db.refresh(message)

        return message


    def get_recent_messages(
            self,
            db: Session,
            *,
            conversation_id: int,
            limit: int,
            scope: str | None = None
    ) -> list[ConversationMessage]:

        """
        读取最近 N 条消息（正序返回）

        **只限窗口，不删除历史**（完整会话留存，trim 仅用于加载窗口）
        scope 过滤预留（chat/task/tool/system 分离）
        """

        query = db.query(ConversationMessage).filter(
            ConversationMessage.conversation_id == int(conversation_id),
        )

        if scope:
            query = query.filter(
                ConversationMessage.scope == scope,
            )

        rows = (
            query.order_by(ConversationMessage.id.desc())
            .limit(limit)
            .all()
        )

        # 转回时间正序
        return list(reversed(rows))

    def delete_by_user(
            self,
            db: Session,
            user_id: int
    ) -> None:

        """
        删除用户的会话及消息（删除用户前清理）
        """

        conversation_ids = [
            row[0]
            for row in db.query(Conversation.id).filter(
                Conversation.user_id == user_id,
            ).all()
        ]

        if conversation_ids:

            (
                db.query(ConversationMessage)
                .filter(
                    ConversationMessage.conversation_id.in_(
                        conversation_ids
                    )
                )
                .delete(
                    synchronize_session=False,
                )
            )

        (
            db.query(Conversation)
            .filter(
                Conversation.user_id == user_id,
            )
            .delete(
                synchronize_session=False,
            )
        )

        db.commit()
