"""
Failure Recovery 测试（P5-5-5）

覆盖：
- 指数退避重试（瞬时错误成功恢复 / 达到上限放弃）
- 熔断器状态机（closed → open → half_open → closed）
- ResilientLLM（重试成功 / 持续失败熔断 / 熔断 open 快速失败）
- LLM 全挂时 Agent 意图路由回退到规则（不阻断）
- HTTP API

用法：
    python -m work_agent.scripts.test_failure_recovery
"""

import time

from types import SimpleNamespace

# 触发 stdout UTF-8 重配置（config.py 导入时生效）
import work_agent.config  # noqa: F401

from work_agent.core.resilience import (
    BreakerOpenError,
    CircuitBreaker,
    ResilientLLM,
    get_breaker,
    retry_with_backoff,
)


class AlwaysFailLLM:

    """
    总是失败的 LLM（统计调用次数）
    """

    def __init__(self, exc=None):
        self.calls = 0
        self.exc = exc or TimeoutError("llm down")

    def invoke(self, prompt, **kwargs):
        self.calls += 1
        raise self.exc


class FlakyThenSuccessLLM:

    """
    前 N 次失败，之后成功
    """

    def __init__(self, fail_count: int = 1):
        self.fail_count = fail_count
        self.calls = 0

    def invoke(self, prompt, **kwargs):
        self.calls += 1
        if self.calls <= self.fail_count:
            raise TimeoutError("transient")
        return SimpleNamespace(content="ok")


def test():

    # ======================
    # 场景1：指数退避重试
    # ======================

    calls = [0]

    def flaky():
        calls[0] += 1
        if calls[0] < 3:
            raise TimeoutError("transient")
        return "ok"

    result = retry_with_backoff(
        flaky,
        max_retries=3,
        base_delay=0.0,
    )

    assert result == "ok", result

    assert calls[0] == 3, calls

    # 达到上限放弃
    calls2 = [0]

    def always_fail():
        calls2[0] += 1
        raise TimeoutError("x")

    raised = False

    try:
        retry_with_backoff(
            always_fail,
            max_retries=2,
            base_delay=0.0,
        )
    except TimeoutError:
        raised = True

    assert raised, "重试耗尽应抛异常"

    assert calls2[0] == 3, calls2  # 1 次 + 2 次重试

    print("场景1 ✅ 指数退避重试（成功恢复 / 上限放弃）")

    # ======================
    # 场景2：熔断器状态机
    # ======================

    breaker = CircuitBreaker(
        name="test-breaker",
        failure_threshold=2,
        cooldown_seconds=60,
        success_threshold=1,
    )

    assert breaker.state == "closed"

    assert breaker.allow() is True

    breaker.record_failure()
    breaker.record_failure()

    assert breaker.state == "open"

    assert breaker.allow() is False, "open 应快速失败"

    assert breaker.total_short_circuits >= 1

    # 冷却期结束 → half_open 探测
    breaker._opened_at = time.monotonic() - 61

    assert breaker.state == "half_open"

    assert breaker.allow() is True, "half_open 允许探测"

    # 探测成功 → 恢复 closed
    breaker.record_success()

    assert breaker.state == "closed", breaker.state

    print("场景2 ✅ 熔断器状态机（closed→open→half_open→closed）")

    # ======================
    # 场景3：ResilientLLM 重试成功
    # ======================

    flaky_llm = FlakyThenSuccessLLM(fail_count=2)

    wrapped = ResilientLLM(
        llm=flaky_llm,
        breaker=CircuitBreaker(name="retry-llm"),
        max_retries=3,
        base_delay=0.0,
    )

    result = wrapped.invoke("你好")

    assert result.content == "ok", result

    assert flaky_llm.calls == 3, flaky_llm.calls

    assert wrapped.breaker.total_retries == 2, wrapped.breaker.total_retries

    print("场景3 ✅ ResilientLLM 瞬时错误重试成功")

    # ======================
    # 场景4：持续失败 → 熔断 open → 快速失败
    # ======================

    failing_llm = AlwaysFailLLM()

    open_breaker = CircuitBreaker(
        name="open-llm",
        failure_threshold=2,
        cooldown_seconds=60,
    )

    wrapped_open = ResilientLLM(
        llm=failing_llm,
        breaker=open_breaker,
        max_retries=0,
    )

    for _ in range(2):
        try:
            wrapped_open.invoke("x")
        except TimeoutError:
            pass

    assert open_breaker.state == "open", open_breaker.state

    # open 后快速失败（不再调用底层 LLM）
    calls_before = failing_llm.calls

    short_circuited = False

    try:
        wrapped_open.invoke("x")
    except BreakerOpenError:
        short_circuited = True

    assert short_circuited, "熔断 open 应抛 BreakerOpenError"

    assert failing_llm.calls == calls_before, "open 不应调用底层 LLM"

    print("场景4 ✅ 持续失败熔断 open + 快速失败")

    # ======================
    # 场景5：LLM 全挂时意图路由回退规则（不阻断）
    # ======================

    from work_agent.agent.router.intent_router import IntentRouter
    from work_agent.agent.schemas import IntentType

    failing_router = IntentRouter(
        llm=ResilientLLM(
            llm=AlwaysFailLLM(),
            breaker=CircuitBreaker(name="router-llm"),
            max_retries=0,
        ),
    )

    result = failing_router.route(
        "财务报销制度是什么",
        user_context={"tenant_id": "1"},
    )

    assert result.intent == IntentType.KNOWLEDGE_QUERY, result.intent

    assert result.tool == "knowledge_tool", result.tool

    print("场景5 ✅ LLM 全挂 → 意图路由规则回退")

    # ======================
    # 场景6：HTTP API
    # ======================

    from fastapi.testclient import TestClient

    from work_agent.main import app

    get_breaker("api:demo")

    client = TestClient(app)

    login = client.post(
        "/api/admin/auth/login",
        json={"username": "admin_A", "password": "test123"},
    )

    headers = {
        "Authorization": f"Bearer {login.json()['access_token']}"
    }

    resp = client.get(
        "/api/admin/resilience/status",
        headers=headers,
    )

    assert resp.status_code == 200, resp.text

    names = {
        item["name"]
        for item in resp.json()["breakers"]
    }

    assert "api:demo" in names, names

    print("场景6 ✅ HTTP API（熔断器状态）")

    print("Failure Recovery 测试全部通过")


if __name__ == "__main__":

    test()
