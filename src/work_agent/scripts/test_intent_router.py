"""
Intent Router 测试

验证：
- LLM 意图分类（知识查询/文档操作/闲聊）
- 结构化输出（IntentResult）
- LLM 异常时规则回退

用法：
    python -m work_agent.scripts.test_intent_router
"""

from work_agent.agent.router.intent_router import IntentRouter
from work_agent.agent.schemas import IntentType


class _FakeFailingLLM:

    """
    模拟 LLM 不可用（用于回退测试）
    """

    def invoke(self, prompt):
        raise RuntimeError("LLM 服务不可用")


def test_fallback():

    router = IntentRouter(
        llm=_FakeFailingLLM()
    )

    # 知识查询关键词 → 回退为 knowledge_query
    result = router.route(
        "财务报销制度是什么"
    )

    assert result.intent == IntentType.KNOWLEDGE_QUERY, result

    assert result.need_tool is True, result

    assert result.tool == "knowledge_tool", result

    assert 0.0 <= result.confidence <= 1.0, result

    # 风险关键词 → 回退为 risk_analysis
    result = router.route(
        "项目延期了3天"
    )

    assert result.intent == IntentType.RISK_ANALYSIS, result

    # 短消息 → small_talk
    result = router.route(
        "在吗"
    )

    assert result.intent == IntentType.SMALL_TALK, result

    print("回退路径 ✅ LLM 异常时规则兜底正常")


def test_real_llm():

    router = IntentRouter()

    user_context = {
        "tenant_id": "1",
        "department": "财务部",
        "role": "员工",
    }

    tenant_context = {
        "tenant_id": "1",
        "name": "企业A",
    }

    # 知识查询
    result = router.route(
        "财务报销制度是什么",
        user_context=user_context,
        tenant_context=tenant_context,
    )

    assert result.intent == IntentType.KNOWLEDGE_QUERY, result

    assert result.need_tool is True, result

    assert result.tool == "knowledge_tool", result

    assert result.confidence >= 0.0, result

    print(
        f"LLM 知识查询 ✅ intent={result.intent} "
        f"confidence={result.confidence} tool={result.tool}"
    )

    # 文档操作
    result = router.route(
        "把文档5的权限改成研发部可见",
        user_context=user_context,
        tenant_context=tenant_context,
    )

    assert result.intent == IntentType.DOCUMENT_OPERATION, result

    assert result.tool == "document_tool", result

    print(
        f"LLM 文档操作 ✅ intent={result.intent} "
        f"tool={result.tool} entities={result.entities}"
    )

    # 闲聊
    result = router.route(
        "你好",
        user_context=user_context,
        tenant_context=tenant_context,
    )

    assert result.intent == IntentType.SMALL_TALK, result

    print(
        f"LLM 闲聊 ✅ intent={result.intent} confidence={result.confidence}"
    )


if __name__ == "__main__":

    test_fallback()

    test_real_llm()

    print("Intent Router 测试全部通过")
