"""
企业微信业务服务

只负责：微信协议、消息收发、身份解析。
Agent 编排统一交给 AgentRuntime。

消息回复由回调层负责主动推送（wechat/client.py send_text_message），
本模块只返回结果 dict，保持可测试。
"""

import logging
import secrets
import time

from uuid import uuid4

from work_agent.agent.runtime import agent_runtime
from work_agent.config import settings
from work_agent.core.audit_logger import audit_logger
from work_agent.data_filter import clean_message
from work_agent.db.session import SessionLocal
from work_agent.repositories.user_repository import UserRepository
from work_agent.wechat.client import wecom_client


logger = logging.getLogger(__name__)


def _auto_create_user(
        wechat_user_id: str
):
    """
    首次消息自动建号（WECHAT_AUTO_CREATE_USER=true 时）

    身份可信（FromUserName 由企微验证）；租户取配置默认值，角色默认 USER。
    密码哈希为随机值 → 无法通过密码登录，只能企微访问。
    """

    info = wecom_client.get_user_info(
        wechat_user_id
    )

    if info.get("errcode") != 0:

        return None

    name = info.get(
        "name",
        wechat_user_id,
    )

    # 懒加载避免循环依赖
    from sqlalchemy.exc import IntegrityError

    from work_agent.services.auth_service import AuthService

    from work_agent.services.rbac_service import RBACService

    db = SessionLocal()

    try:

        repo = UserRepository()

        try:

            user = repo.create(
                db,
                username=f"wx_{wechat_user_id}",
                password_hash=AuthService.hash_password(
                    secrets.token_urlsafe(32)
                ),
                department="",
                role="员工",
                real_name=name,
                wechat_user_id=wechat_user_id,
                # 单公司模型：默认落公司租户（未显式配置则用 default_tenant_id）
                tenant_id=(
                    settings.wechat_default_tenant_id
                    or settings.default_tenant_id
                ),
            )

        except IntegrityError:

            # 并发/企微重试竞态：他人已建号（撞 username/wechat 唯一）→
            # 回滚后返回已存在者（find-or-create），不报错、不产生重复用户
            db.rollback()

            existing = repo.get_by_wechat_user_id(
                db,
                wechat_user_id,
            )

            if existing:

                return existing

            raise

        RBACService().assign_role(
            db,
            user.id,
            "USER",
        )

        return user

    finally:

        db.close()


def _resolve_user(
        wechat_user_id: str
):
    """
    企微 userid → 系统用户；未绑定按配置自动建号或返回 None
    """

    db = SessionLocal()

    try:

        user = UserRepository().get_by_wechat_user_id(
            db,
            wechat_user_id,
        )

        if user:

            return user

        if settings.wechat_auto_create_user:

            return _auto_create_user(
                wechat_user_id
            )

        return None

    finally:

        db.close()


def process_message(
    message: dict
):

    """
    处理企业微信消息

    流程：解析消息 → 身份解析 → AgentRuntime 执行

    返回：
        {
            "response": str,          # Agent 回复（已绑定用户）
            "request_id": str,
        }
    或错误：
        {
            "error": str,
            "user": str,
            "message": str,           # 需主动推送给用户的提示
        }
    """

    request_id = str(uuid4())

    started = time.monotonic()

    try:

        cleaned = clean_message(
            message
        )

        wechat_user_id = cleaned["user"]

        logger.info(
            "process_message: wechat_user_id=%s content=%s",
            wechat_user_id,
            cleaned["content"][:60],
        )

        # ======================
        # 身份解析
        # FromUserName → users.wechat_user_id → tenant/department/role
        # ======================

        user = _resolve_user(
            wechat_user_id
        )

        logger.info(
            "身份解析结果: found=%s user_id=%s tenant=%s",
            bool(user),
            getattr(user, "id", None),
            getattr(user, "tenant_id", None),
        )

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

        logger.info(
            "调用 agent_runtime.execute: user_id=%s",
            user.id,
        )

        result = agent_runtime.execute(
            message=cleaned["content"],
            user=user,
            channel="wechat",
        )

        logger.info(
            "agent_runtime 返回: keys=%s response_len=%d",
            sorted(result.keys()),
            len(result.get("response") or ""),
        )

        return result

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
