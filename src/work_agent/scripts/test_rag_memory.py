"""
RAG 会话记忆测试（6-3.txt 轻量 State，Phase 1-4）

Part A  数据层 + context window（保存完整历史，读取限窗口）
Part B  query rewrite（指代词优先 _is_follow_up）
Part C  统一上下文共享（制度查询后可创建任务）
Part D  生产优化（跨用户隔离 / scope 字段 / 异常容错）

用法：
    python -m work_agent.scripts.test_rag_memory
"""

# 副作用：触发 config.py stdout UTF-8 重配置（Windows GBK）
import work_agent.config  # noqa: F401

from work_agent.db.session import SessionLocal
from work_agent.services.conversation_service import conversation_service
from work_agent.services.conversation_memory_service import (
    conversation_memory_service,
)


TEST_USER_A = 999901
TEST_USER_B = 999902


def _get_conv(tenant_id, user_id, channel="wechat"):
    return conversation_service.get_or_create(
        tenant_id=tenant_id,
        user_id=user_id,
        channel=channel,
    )


def _cleanup():
    from sqlalchemy import text
    from work_agent.db.session import engine
    with engine.begin() as c:
        c.execute(
            text(
                "DELETE FROM conversation_messages "
                "WHERE user_id IN (:a, :b)"
            ),
            {"a": TEST_USER_A, "b": TEST_USER_B},
        )
        c.execute(
            text(
                "DELETE FROM conversations "
                "WHERE user_id IN (:a, :b)"
            ),
            {"a": TEST_USER_A, "b": TEST_USER_B},
        )


def test_a_storage_and_window():
    """Part A：历史保存 + context window（DB 保留完整，读取限窗口）"""
    cid = _get_conv("1", TEST_USER_A)

    # 写 8 轮（16 条），窗口默认 6 轮
    for i in range(8):
        conversation_memory_service.append_round(
            cid,
            f"问题{i}",
            f"回答{i}",
        )

    # 读取窗口：6 轮 = 12 条
    hist = conversation_memory_service.get_recent(cid)
    assert len(hist) == 12, f"窗口应为 12 条，实际 {len(hist)}"

    # 正序：最早是第 3 轮 user（问题2）
    assert hist[0].type == "human", hist[0].type
    assert "问题2" in str(hist[0].content), str(hist[0].content)

    # DB 保留完整：16 条（不删历史）
    db = SessionLocal()
    try:
        from work_agent.db.models import ConversationMessage
        total = db.query(ConversationMessage).filter(
            ConversationMessage.conversation_id == cid
        ).count()
        assert total == 16, f"DB 应保留 16 条，实际 {total}"
    finally:
        db.close()

    # adapter：role → BaseMessage 类型
    assert hist[1].type == "ai", hist[1].type
    assert hist[0].content == "问题2", hist[0].content

    # serialize
    s = conversation_memory_service.serialize_history(hist)
    assert "用户：问题2" in s, s
    assert "助手：回答2" in s, s

    print("✓ PartA 历史保存 + context window + adapter")


def test_a2_empty_and_scope():
    """Part A2：空会话防御 + scope 字段"""
    # 无会话 id → []
    assert conversation_memory_service.get_recent(None) == []
    assert conversation_memory_service.get_recent("") == []

    # scope=task 写入，读取 chat 不受影响
    cid = _get_conv("1", TEST_USER_A)
    conversation_memory_service.append(
        cid,
        role="assistant",
        content="任务已创建",
        scope="task",
        tenant_id="1",
        user_id=TEST_USER_A,
    )
    chat_hist = conversation_memory_service.get_recent(cid, scope="chat")
    assert not any(
        "任务已创建" in str(m.content)
        for m in chat_hist
    ), "chat scope 不应含 task 消息"

    db = SessionLocal()
    try:
        from work_agent.db.models import ConversationMessage
        task_msgs = db.query(ConversationMessage).filter(
            ConversationMessage.conversation_id == cid,
            ConversationMessage.scope == "task",
        ).all()
        assert len(task_msgs) == 1
        assert task_msgs[0].tool_name is None
    finally:
        db.close()

    print("✓ PartA2 空会话防御 + scope 字段")


def test():
    print("== RAG 会话记忆测试（Phase 1）==")
    _cleanup()
    try:
        test_a_storage_and_window()
        test_a2_empty_and_scope()
    finally:
        _cleanup()
    print("RAG 会话记忆测试（Phase 1）通过")


if __name__ == "__main__":
    test()
