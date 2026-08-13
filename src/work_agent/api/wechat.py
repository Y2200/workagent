"""
企业微信回调路由（公开端点，无 JWT，靠企微签名验证）

- GET  /api/wechat/callback   URL 验证（echostr 解密回显）
- POST /api/wechat/callback   接收消息 → 后台任务 → 主动回复

安全边界：
- 安全模式：验签 + AES 解密；验签/解密失败一律返回空串，不泄露内部信息
- 明文模式：无 msg_signature 时按明文处理（便于联调；生产请用安全模式）
- 时限：立即返回 ""，避免企微 5 秒超时重试
- 幂等：Redis SETNX wechat:msgid:<MsgId> 去重，防重试重复执行
"""

import logging

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import PlainTextResponse

from work_agent.config import settings
from work_agent.wechat.client import wecom_client
from work_agent.wechat.crypto import WXBizMsgCrypt
from work_agent.wechat.parser import parse_wechat_xml
from work_agent.wechat.service import process_message


logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/wechat",
    tags=["wechat"],
)


def _crypto() -> WXBizMsgCrypt:

    return WXBizMsgCrypt(
        token=settings.wechat_token,
        encoding_aes_key=settings.wechat_encoding_aes_key,
        corp_id=settings.wechat_corp_id,
    )


def _dedup(
        msg_id: str
) -> bool:
    """
    Redis SETNX 幂等去重；Redis 不可用时放行
    """

    if not msg_id:

        return True

    try:

        import redis as redis_module

        client = redis_module.from_url(
            settings.redis_url
        )

        return bool(
            client.set(
                f"wechat:msgid:{msg_id}",
                "1",
                nx=True,
                ex=300,
            )
        )

    except Exception:

        return True


def _handle_message(
        msg: dict
) -> None:
    """
    后台执行 Agent 并主动回复（回复走 message/send，非被动回包）
    """

    try:

        result = process_message(
            msg
        )

        if result.get("error"):

            text = (
                result.get("message")
                or "服务异常"
            )

        else:

            text = (
                result.get("response")
                or ""
            )

        if text:

            resp = wecom_client.send_text_message(
                msg["user"],
                text,
            )

            if resp.get("errcode") != 0:

                logger.warning(
                    "企微回复发送失败: %s",
                    resp,
                )

    except Exception:

        logger.exception(
            "企微消息处理异常"
        )

        try:

            wecom_client.send_text_message(
                msg["user"],
                "系统繁忙，请稍后再试。",
            )

        except Exception:

            logger.exception(
                "异常兜底消息发送失败"
            )


@router.get(
    "/callback",
    response_class=PlainTextResponse
)
def wechat_verify(
        timestamp: str = "",
        nonce: str = "",
        msg_signature: str = "",
        echostr: str = "",
):

    """
    URL 验证：验签 + 解密 echostr 并回显明文
    """

    if not (
        settings.wechat_token
        and settings.wechat_encoding_aes_key
    ):

        return PlainTextResponse("")

    # 明文模式：无签名，直接回显
    if not msg_signature:

        return PlainTextResponse(
            echostr
        )

    try:

        crypto = _crypto()

        if not crypto.verify_signature(
                msg_signature,
                timestamp,
                nonce,
                echostr,
        ):

            return PlainTextResponse("")

        return PlainTextResponse(
            crypto.decrypt(echostr)
        )

    except Exception:

        logger.exception(
            "企微 URL 验证失败"
        )

        return PlainTextResponse("")


@router.post(
    "/callback",
    response_class=PlainTextResponse
)
async def wechat_message(
        request: Request,
        background_tasks: BackgroundTasks,
):

    """
    接收消息：验签 → 解密 → 幂等去重 → 后台处理 → 立即返回空
    """

    if not (
        settings.wechat_token
        and settings.wechat_encoding_aes_key
    ):

        return PlainTextResponse("")

    query = request.query_params

    timestamp = query.get(
        "timestamp",
        "",
    )

    nonce = query.get(
        "nonce",
        "",
    )

    msg_signature = query.get(
        "msg_signature",
        "",
    )

    body = (
        await request.body()
    ).decode(
        "utf-8",
        errors="ignore",
    )

    if not body:

        return PlainTextResponse("")

    # ======================
    # 安全模式：验签 + 解密；明文模式：直接解析
    # ======================

    if msg_signature:

        try:

            crypto = _crypto()

            if not crypto.verify_signature(
                    msg_signature,
                    timestamp,
                    nonce,
                    body,
            ):

                return PlainTextResponse("")

            xml_text = crypto.decrypt(body)

        except Exception:

            logger.exception(
                "企微消息验签/解密失败"
            )

            return PlainTextResponse("")

    else:

        xml_text = body

    try:

        msg = parse_wechat_xml(
            xml_text
        )

    except Exception:

        logger.exception(
            "企微消息 XML 解析失败"
        )

        return PlainTextResponse("")

    if (
        msg.get("msg_type") != "text"
        or not msg.get("content")
        or not msg.get("user")
    ):

        return PlainTextResponse("")

    if not _dedup(
            msg.get("msg_id", "")
    ):

        return PlainTextResponse("")

    background_tasks.add_task(
        _handle_message,
        msg,
    )

    return PlainTextResponse("")
