"""
企业微信消息发送（兼容门面）

统一实现见 wechat/client.py（含 access_token Redis 缓存）。
本模块保留原接口，避免破坏既有引用。
"""

from work_agent.wechat.client import wecom_client


def get_access_token() -> str:

    return wecom_client.get_access_token()


def send_text_message(
        user_id: str,
        content: str
) -> dict:

    return wecom_client.send_text_message(
        user_id,
        content,
    )
