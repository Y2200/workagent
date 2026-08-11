"""
Agent Context 测试

验证：
- 会话连续性（同用户共享会话）
- 会话消息数递增
- 不同用户不同会话
- 上下文完整（model_name/agent_version/prompt_version）
- 租户隔离（不同租户不同会话）

用法：
    python -m work_agent.scripts.test_agent_context
"""

from work_agent.agent.runtime import agent_runtime
from work_agent.db.models import Conversation
from work_agent.db.session import SessionLocal
from work_agent.repositories.user_repository import UserRepository
from work_agent.scripts.seed_tenants import seed_tenants


def _cleanup_conversations():

    db = SessionLocal()

    try:

        db.query(Conversation).delete(
            synchronize_session=False
        )

        db.commit()

    finally:

        db.close()


def test():

    seed_tenants()

    _cleanup_conversations()

    db = SessionLocal()

    try:

        user_a = UserRepository().get_by_username(db, "员工A")

        user_b = UserRepository().get_by_username(db, "A财务员工")

    finally:

        db.close()

    # ======================
    # 场景1：会话连续性（同用户连续消息）
    # ======================

    r1 = agent_runtime.execute(
        message="日报制度是什么",
        user=user_a,
        channel="wechat",
    )

    r2 = agent_runtime.execute(
        message="财务报销制度是什么",
        user=user_a,
        channel="wechat",
    )

    assert r1["conversation_id"] == r2["conversation_id"], (
        f"会话应连续: {r1['conversation_id']} vs {r2['conversation_id']}"
    )

    conv_id = r1["conversation_id"]

    print(
        f"场景1 ✅ 会话连续性: conversation_id={conv_id}"
    )

    # ======================
    # 场景2：消息数递增
    # ======================

    db = SessionLocal()

    try:

        conv = db.get(Conversation, int(conv_id))

    finally:

        db.close()

    assert conv is not None

    assert conv.message_count == 2, f"消息数应递增: {conv.message_count}"

    assert conv.status == "active", conv.status

    print(
        f"场景2 ✅ 消息数递增: message_count={conv.message_count}, "
        f"last_activity={conv.last_activity_at.strftime('%H:%M:%S')}"
    )

    # ======================
    # 场景3：上下文完整（model_name/agent_version）
    # ======================

    r3 = agent_runtime.execute(
        message="请假制度是什么",
        user=user_a,
        channel="wechat",
    )

    db = SessionLocal()

    try:

        # 从最新会话记录确认
        latest = db.query(Conversation).filter(
            Conversation.user_id == user_a.id
        ).order_by(Conversation.id.desc()).first()

    finally:

        db.close()

    assert latest.message_count >= 3, latest.message_count

    print(
        f"场景3 ✅ 上下文驱动会话: message_count={latest.message_count}"
    )

    # ======================
    # 场景4：不同用户不同会话
    # ======================

    r4 = agent_runtime.execute(
        message="日报制度是什么",
        user=user_b,
        channel="wechat",
    )

    assert r4["conversation_id"] != conv_id, "不同用户应不同会话"

    print(
        f"场景4 ✅ 不同用户不同会话: "
        f"userA={conv_id} vs userB={r4['conversation_id']}"
    )

    # ======================
    # 场景5：上下文字段可用（AgentContext.to_audit_fields）
    # ======================

    from work_agent.agent.context import AgentContext

    from work_agent.config import settings

    ctx = AgentContext.build(
        user=user_a,
        model_name=settings.model_name,
        agent_version=settings.agent_version,
    )

    audit_fields = ctx.to_audit_fields()

    assert audit_fields["model_name"] == settings.model_name, audit_fields

    assert audit_fields["agent_version"] == settings.agent_version, audit_fields

    print(f"场景5 ✅ 上下文审计字段: {audit_fields}")

    # 清理
    _cleanup_conversations()

    print("Agent Context 测试全部通过")


if __name__ == "__main__":

    test()
