"""
企业微信业务服务

只负责：微信协议、消息收发、身份解析。
Agent 编排统一交给 AgentRuntime。
"""

import time

from uuid import uuid4

from work_agent.agent.runtime import agent_runtime
from work_agent.core.audit_logger import audit_logger
from work_agent.data_filter import clean_message
from work_agent.db.session import SessionLocal
from work_agent.repositories.user_repository import UserRepository


def process_message(
    message: dict
):

    """
    处理企业微信消息

    流程：解析消息 → 身份解析 → AgentRuntime 执行
    """

    request_id = str(uuid4())

    started = time.monotonic()

    try:

        cleaned = clean_message(
            message
        )

        wechat_user_id = cleaned["user"]

        # ======================
        # 身份解析
        # FromUserName → users.wechat_user_id → tenant/department/role
        # ======================

        db = SessionLocal()

        try:

            user = UserRepository().get_by_wechat_user_id(
                db,
                wechat_user_id
            )

        finally:

            db.close()

        if not user:

            ctx = audit_logger.log_request(
                request_id=request_id,
                channel="wechat",
                question=cleaned["content"],
            )

            audit_logger.log_error(
                ctx,
                status="denied",
                error_type="user_not_registered",
                error_message="企业微信账号未关联到系统",
                latency_ms=(
                    time.monotonic() - started
                ) * 1000,
            )

            return {
                "error": "用户未注册",
                "user": wechat_user_id,
                "message": (
                    "您的企业微信账号未关联到系统，"
                    "请联系管理员开通后再提问。"
                ),
            }

        # ======================
        # Agent 执行（统一 Runtime）
        # ======================

        return agent_runtime.execute(
            message=cleaned["content"],
            user=user,
            channel="wechat",
        )

    except Exception as exc:

        ctx = audit_logger.log_request(
            request_id=request_id,
            channel="wechat",
            question=message.get(
                "content",
                "",
            ),
        )

        audit_logger.log_error(
            ctx,
            error_type=type(exc).__name__,
            error_message=str(exc),
            latency_ms=(
                time.monotonic() - started
            ) * 1000,
        )

        raise
