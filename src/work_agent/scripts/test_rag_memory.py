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


def test_b_query_rewrite():
    """Part B：query rewrite（指代词优先 _is_follow_up）"""
    from langchain_core.messages import AIMessage, HumanMessage

    from work_agent.agent.query_rewriter import QueryRewriter

    # fake LLM 返回固定改写
    class _FakeLLM:
        def __init__(self, out):
            self.out = out
        def invoke(self, prompt):
            class _R:
                content = self.out
            return _R()

    # failing LLM（抛异常 → 走确定性兜底）
    class _FailingLLM:
        def invoke(self, prompt):
            raise RuntimeError("llm down")

    history = [
        HumanMessage(content="差旅住宿标准是什么"),
        AIMessage(content="员工每晚400元"),
    ]

    rewriter = QueryRewriter(llm=_FakeLLM("公司差旅经理住宿标准"))

    # 无历史 → 原样
    assert rewriter.rewrite_query("那经理呢？", []) == "那经理呢？"

    # 独立问题 → 原样（_is_follow_up False）
    assert rewriter.rewrite_query("差旅住宿标准是什么", history) == "差旅住宿标准是什么"

    # 追问 + fake LLM → 用 LLM 输出
    assert rewriter.rewrite_query("那经理呢？", history) == "公司差旅经理住宿标准"

    # 追问 + failing LLM → 确定性兜底（含实体"经理" + 基底"差旅住宿标准"）
    fallback = QueryRewriter(llm=_FailingLLM()).rewrite_query("那经理呢？", history)
    assert "经理" in fallback and "差旅" in fallback, fallback

    # _is_follow_up 指代词判定
    assert QueryRewriter._is_follow_up("那经理呢？") is True
    assert QueryRewriter._is_follow_up("这个制度有效期呢") is True
    assert QueryRewriter._is_follow_up("多少钱？") is True
    assert QueryRewriter._is_follow_up("差旅住宿标准是什么") is False
    assert QueryRewriter._is_follow_up("报销流程怎么走") is False

    print("✓ PartB query rewrite（指代词/独立问题/LLM/兜底）")


def test_b2_rewrite_retrieval():
    """Part B2：rewrite 后仍能检索（集成，确定性）"""
    import time

    from langchain_core.messages import AIMessage, HumanMessage

    from work_agent.agent.query_rewriter import QueryRewriter
    from work_agent.core.container import document_service, rag_service
    from work_agent.repositories.document_repository import DocumentRepository

    class _FailingLLM:
        def invoke(self, prompt):
            raise RuntimeError("llm down")

    # 上传差旅制度文档（租户1）
    content = (
        "公司差旅住宿标准制度：\n"
        "1. 员工出差住宿标准：每晚不超过400元。\n"
        "2. 经理出差住宿标准：每晚不超过600元。\n"
        "3. 报销需提供发票。"
    )
    doc = document_service.upload(
        filename="差旅住宿标准制度.md",
        data=content.encode("utf-8"),
        category="制度",
        uploader="admin",
        tenant_id="1",
    )

    # 等 ready
    db = SessionLocal()
    try:
        repo = DocumentRepository()
        start = time.time()
        status = "processing"
        while time.time() - start < 60:
            db.expire_all()
            d = repo.get_by_id(db, doc.id)
            if d and d.status in ("ready", "failed"):
                status = d.status
                break
            time.sleep(1)
        assert status == "ready", f"文档未 ready: {status}"
    finally:
        db.close()

    try:
        history = [
            HumanMessage(content="员工出差住宿标准是什么"),
            AIMessage(content="每晚不超过400元"),
        ]
        rewriter = QueryRewriter(llm=_FailingLLM())
        rewritten = rewriter.rewrite_query("那经理呢？", history)
        assert "经理" in rewritten, rewritten

        # rewrite 后检索 → 命中经理标准片段
        meta = rag_service.search_with_meta(
            rewritten,
            top_k=5,
            user_context={
                "tenant_id": "1",
                "department": "研发部",
                "role": "员工",
            },
        )
        texts = [h.get("text", "") for h in meta["results"]]
        assert meta["candidates"] > 0, meta
        assert any(
            "经理" in t and "600" in t
            for t in texts
        ), f"应命中经理标准，实际: {texts[:2]}"

        print("✓ PartB2 rewrite 后检索命中经理标准")
    finally:
        document_service.delete(doc.id, tenant_id="1")


def test_c_task_shared_context():
    """Part C：任务链路共享上下文（chat_history 辅助理解，业务决策隔离）"""
    from langchain_core.messages import AIMessage, HumanMessage

    from work_agent.core.container import task_service

    # 构造历史：上一轮查了制度
    history = [
        HumanMessage(content="差旅报销制度是什么"),
        AIMessage(content="根据制度，员工住宿标准每晚不超过400元"),
    ]

    # preview_create_task 接受 chat_history 不破坏原有解析
    # 业务决策隔离：执行人/日期仍确定性解析，不因历史改变
    r = task_service.preview_create_task(
        creator_id=999999,
        creator_tenant_id="1",
        content="给A研发员工安排安全培训任务，下周五完成",
        chat_history=history,
    )
    assert r["status"] == "awaiting_confirmation", r
    draft = r["draft"]
    assert draft["employee_name"] == "A研发员工", draft  # 确定性解析，不因历史变
    assert draft["deadline"] is not None, draft  # 下周五解析

    # 无 chat_history 时行为不变（向后兼容）
    r2 = task_service.preview_create_task(
        creator_id=999999,
        creator_tenant_id="1",
        content="给A研发员工安排接口开发任务",
        chat_history=None,
    )
    assert r2["status"] == "awaiting_confirmation", r2
    assert "接口开发" in r2["draft"]["title"], r2

    # 清理草稿
    task_service.cancel_pending_create(creator_id=999999)

    print("✓ PartC 任务链路共享上下文（业务决策隔离）")


def test():
    print("== RAG 会话记忆测试（Phase 1-3）==")
    _cleanup()
    try:
        test_a_storage_and_window()
        test_a2_empty_and_scope()
        test_b_query_rewrite()
        test_b2_rewrite_retrieval()
        test_c_task_shared_context()
    finally:
        _cleanup()
    print("RAG 会话记忆测试（Phase 1-3）通过")


if __name__ == "__main__":
    test()
