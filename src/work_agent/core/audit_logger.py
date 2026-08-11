"""
统一审计日志

业务层只调用：
    audit_logger.log_request(...)
    audit_logger.log_success(...)
    audit_logger.log_error(...)

日志逻辑不散落在业务代码中。
"""

import time

from dataclasses import dataclass

from langchain_core.callbacks import BaseCallbackHandler

from work_agent.db.session import SessionLocal
from work_agent.repositories.agent_log_repository import AgentLogRepository


@dataclass
class AuditContext:

    """
    一次问答审计上下文
    """

    log_id: int

    request_id: str

    started_at: float  # time.monotonic()


class TokenUsageCallback(BaseCallbackHandler):

    """
    聚合一次问答中所有 LLM 调用的 token 用量

    通过 workflow.invoke(config={"callbacks": [...]}) 传入
    """

    def __init__(self):

        self.input_tokens = 0

        self.output_tokens = 0

        self.calls = 0


    def on_llm_end(
            self,
            response,
            **kwargs
    ) -> None:

        try:

            for generations in response.generations:

                for generation in generations:

                    message = getattr(
                        generation,
                        "message",
                        None
                    )

                    usage = getattr(
                        message,
                        "usage_metadata",
                        None
                    )

                    if not usage:
                        continue

                    self.input_tokens += int(
                        usage.get(
                            "input_tokens",
                            0
                        )
                        or 0
                    )

                    self.output_tokens += int(
                        usage.get(
                            "output_tokens",
                            0
                        )
                        or 0
                    )

                    self.calls += 1

        except Exception:
            pass


    @property
    def total(self) -> int:

        return self.input_tokens + self.output_tokens


class AuditLogger:

    """
    统一审计日志器
    """

    def __init__(
            self,
            repository: AgentLogRepository | None = None
    ):

        self.repository = repository or AgentLogRepository()


    def log_request(
            self,
            *,
            request_id: str,
            tenant_id: str = "",
            user_id: int | None = None,
            department: str = "",
            role: str = "",
            channel: str = "wechat",
            question: str = "",
            agent_version: str = "",
            model_name: str = ""
    ) -> AuditContext:

        """
        记录请求开始（status=processing），返回审计上下文
        """

        db = SessionLocal()

        try:

            log = self.repository.create(
                db,
                request_id=request_id,
                tenant_id=tenant_id,
                user_id=user_id,
                department=department,
                role=role,
                channel=channel,
                question=question,
                status="processing",
                agent_version=agent_version,
                model_name=model_name,
            )

            return AuditContext(
                log_id=log.id,
                request_id=request_id,
                started_at=time.monotonic(),
            )

        finally:

            db.close()


    def log_success(
            self,
            ctx: AuditContext,
            *,
            answer: str = "",
            intent: str = "",
            retrieval_documents: list | None = None,
            status: str = "success",
            latency_ms: int | None = None,
            token_usage: int = 0,
            prompt_version: str = "",
            intent_confidence: float = 0.0,
            tools_called: list | None = None
    ) -> None:

        """
        记录成功完成（含权限拒绝 denied 场景）
        """

        db = SessionLocal()

        try:

            self.repository.complete(
                db,
                log_id=ctx.log_id,
                status=status,
                answer=answer,
                intent=intent,
                retrieval_documents=retrieval_documents,
                latency_ms=latency_ms,
                token_usage=token_usage,
                prompt_version=prompt_version,
                intent_confidence=intent_confidence,
                tools_called=tools_called,
            )

        finally:

            db.close()


    def log_error(
            self,
            ctx: AuditContext,
            *,
            error_type: str = "",
            error_message: str = "",
            status: str = "failed",
            latency_ms: int | None = None,
            answer: str = ""
    ) -> None:

        """
        记录失败（含认证拒绝 denied 场景）
        """

        db = SessionLocal()

        try:

            self.repository.complete(
                db,
                log_id=ctx.log_id,
                status=status,
                answer=answer,
                error_type=error_type,
                error_message=error_message,
                latency_ms=latency_ms,
            )

        finally:

            db.close()


# 全局单例
audit_logger = AuditLogger()
