"""
故障恢复（Resilience）

- retry_with_backoff：瞬时错误指数退避重试
- CircuitBreaker：closed → open（错误阈值）→ half_open（冷却后探测）→ closed
- ResilientLLM：对 LLM invoke 施加重试 + 熔断的透明包装

设计：熔断 open 时快速失败（BreakerOpenError），
上层 Agent 捕获后走确定性回退，避免在故障服务上反复超时。
"""

import time

# 瞬时错误（可重试）
TRANSIENT_EXCEPTIONS = (
    TimeoutError,
    ConnectionError,
    OSError,
)

try:

    from openai import APIConnectionError, APITimeoutError, RateLimitError

    TRANSIENT_EXCEPTIONS = TRANSIENT_EXCEPTIONS + (
        APIConnectionError,
        APITimeoutError,
        RateLimitError,
    )

except ImportError:
    pass


class BreakerOpenError(RuntimeError):

    """
    熔断打开：快速失败
    """


class CircuitBreaker:

    """
    熔断器（进程内状态）
    """

    def __init__(
            self,
            name: str,
            failure_threshold: int = 5,
            cooldown_seconds: float = 60.0,
            success_threshold: int = 2
    ):

        self.name = name

        self.failure_threshold = failure_threshold

        self.cooldown_seconds = cooldown_seconds

        self.success_threshold = success_threshold

        # closed / open / half_open
        self._state = "closed"

        self._failure_count = 0

        self._success_count = 0

        self._opened_at: float | None = None

        # 观测计数
        self.total_calls = 0

        self.total_failures = 0

        self.total_retries = 0

        self.total_short_circuits = 0


    @property
    def state(self) -> str:

        # 冷却期结束：自动进入 half_open 探测
        if (
                self._state == "open"
                and self._opened_at is not None
                and (time.monotonic() - self._opened_at)
                >= self.cooldown_seconds
        ):

            self._state = "half_open"

        return self._state


    def allow(self) -> bool:

        """
        是否允许调用（open → 拒绝快速失败）
        """

        self.total_calls += 1

        if self.state == "open":

            self.total_short_circuits += 1

            return False

        return True


    def record_success(self) -> None:

        self._success_count += 1

        if self.state == "half_open":

            if self._success_count >= self.success_threshold:
                self._reset()

        else:

            # closed 下成功：清空失败计数
            self._failure_count = 0


    def record_failure(self) -> None:

        self.total_failures += 1

        self._success_count = 0

        if self.state == "half_open":

            # 探测失败 → 重新打开
            self._state = "open"

            self._opened_at = time.monotonic()

            self._failure_count = 0

        else:

            self._failure_count += 1

            if self._failure_count >= self.failure_threshold:

                self._state = "open"

                self._opened_at = time.monotonic()


    def note_retry(self) -> None:

        self.total_retries += 1


    def status(self) -> dict:

        return {
            "name": self.name,
            "state": self.state,
            "failure_threshold": self.failure_threshold,
            "cooldown_seconds": self.cooldown_seconds,
            "failure_count": self._failure_count,
            "success_count": self._success_count,
            "total_calls": self.total_calls,
            "total_failures": self.total_failures,
            "total_retries": self.total_retries,
            "total_short_circuits": self.total_short_circuits,
        }


    def _reset(self) -> None:

        self._state = "closed"

        self._failure_count = 0

        self._success_count = 0

        self._opened_at = None


def retry_with_backoff(
        fn,
        max_retries: int = 1,
        base_delay: float = 0.2,
        backoff_factor: float = 2.0,
        retry_exceptions=TRANSIENT_EXCEPTIONS,
        on_retry=None
):
    """
    指数退避重试：仅对瞬时错误重试
    """

    attempt = 0

    while True:

        try:

            return fn()

        except retry_exceptions:

            if attempt >= max_retries:
                raise

            attempt += 1

            if on_retry:
                on_retry()

            time.sleep(
                base_delay * (backoff_factor ** (attempt - 1))
            )


class ResilientLLM:

    """
    带重试 + 熔断的 LLM 透明包装

    接口与 ChatOpenAI 一致（invoke），失败/熔断抛异常由上层回退
    """

    def __init__(
            self,
            llm,
            breaker: CircuitBreaker | None = None,
            max_retries: int = 1,
            base_delay: float = 0.2
    ):

        self.llm = llm

        self.breaker = breaker or CircuitBreaker(
            name="llm",
        )

        self.max_retries = max_retries

        self.base_delay = base_delay


    def invoke(self, prompt, **kwargs):

        if not self.breaker.allow():

            raise BreakerOpenError(
                f"circuit breaker open: {self.breaker.name}"
            )

        try:

            return retry_with_backoff(
                lambda: self.llm.invoke(prompt, **kwargs),
                max_retries=self.max_retries,
                base_delay=self.base_delay,
                on_retry=self.breaker.note_retry,
            )

        except TRANSIENT_EXCEPTIONS:

            self.breaker.record_failure()

            raise

        except Exception:

            self.breaker.record_failure()

            raise

        else:

            self.breaker.record_success()


# ======================
# 全局熔断器注册表
# ======================

_breaker_registry: dict[str, CircuitBreaker] = {}


def get_breaker(
        name: str,
        *,
        failure_threshold: int = 5,
        cooldown_seconds: float = 60.0
) -> CircuitBreaker:

    if name not in _breaker_registry:

        _breaker_registry[name] = CircuitBreaker(
            name=name,
            failure_threshold=failure_threshold,
            cooldown_seconds=cooldown_seconds,
        )

    return _breaker_registry[name]


def list_breaker_statuses() -> list[dict]:

    return [
        breaker.status()
        for breaker in _breaker_registry.values()
    ]
