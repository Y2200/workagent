"""
运行时健康指标（进程内计数器）

Runtime 各终态调用 record() 递增；提供 snapshot 供健康端点输出
"""

import time


class HealthMetrics:

    """
    进程内运行时指标
    """

    def __init__(self):

        self.requests = 0

        self.errors = 0

        self.denied = 0

        self.total_latency_ms = 0.0

        self.total_tokens = 0

        self.started_at = time.time()


    def record(
            self,
            *,
            status: str,
            latency_ms: int,
            tokens: int = 0
    ) -> None:

        """
        记录一次请求终态

        status: success / denied / failed
        """

        self.requests += 1

        self.total_latency_ms += latency_ms

        self.total_tokens += int(tokens or 0)

        if status in ("failed", "error"):
            self.errors += 1

        elif status == "denied":
            self.denied += 1


    def snapshot(self) -> dict:

        requests = self.requests

        return {
            "uptime_seconds": int(
                time.time() - self.started_at
            ),
            "requests": requests,
            "errors": self.errors,
            "denied": self.denied,
            "error_rate": round(
                self.errors / requests,
                4,
            )
            if requests
            else 0.0,
            "avg_latency_ms": round(
                self.total_latency_ms / requests,
                1,
            )
            if requests
            else 0.0,
            "total_tokens": self.total_tokens,
        }


# 全局单例
health_metrics = HealthMetrics()
