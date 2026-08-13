"""
企业微信 API 客户端（统一入口）

收编原 wechat/sender.py + wechat/auth.py：
- access_token 缓存：Redis（生产）→ 内存兜底，避免每次请求 gettoken
- send_text_message：主动发应用消息（回复走此通道，非被动回包）
- get_user_info：自动建号时拉取企微用户资料

Redis 不可用时优雅降级（同 health_service 的可选依赖策略）。
"""

import time

import requests

from work_agent.config import settings


_BASE = "https://qyapi.weixin.qq.com/cgi-bin"


class WeComClient:

    def __init__(
            self
    ):

        self._token_cache = {}

    # ======================
    # 缓存 / Redis
    # ======================

    def _redis(self):

        """
        返回 Redis 客户端；不可用返回 None
        """

        try:

            import redis as redis_module

            client = redis_module.from_url(
                settings.redis_url
            )

            client.ping()

            return client

        except Exception:

            return None

    def _cache_key(
            self
    ) -> str:

        return (
            "wechat:access_token:"
            f"{settings.wechat_corp_id}:"
            f"{settings.wechat_agent_id}"
        )

    # ======================
    # access_token
    # ======================

    def get_access_token(
            self
    ) -> str:

        token = self._cache_get()

        if token:

            return token

        response = requests.get(
            f"{_BASE}/gettoken",
            params={
                "corpid": settings.wechat_corp_id,
                "corpsecret": settings.wechat_secret,
            },
            timeout=10,
        )

        data = response.json()

        if data.get("errcode") != 0:

            raise Exception(
                f"获取 access_token 失败: {data}"
            )

        token = data["access_token"]

        # 提前 200s 过期，避免边界失效
        expire = int(
            data.get("expires_in", 7200)
        ) - 200

        self._cache_set(
            token,
            max(expire, 60),
        )

        return token

    def _cache_get(
            self
    ) -> str | None:

        key = self._cache_key()

        # 内存兜底（Redis 不可用时）
        cached = self._token_cache.get(key)

        if cached and cached["expire"] > time.time():

            return cached["token"]

        redis_client = self._redis()

        if redis_client:

            try:

                return redis_client.get(key)

            except Exception:

                return None

        return None

    def _cache_set(
            self,
            token: str,
            expire: int
    ) -> None:

        key = self._cache_key()

        # 内存兜底
        self._token_cache[key] = {
            "token": token,
            "expire": time.time() + expire,
        }

        redis_client = self._redis()

        if redis_client:

            try:

                redis_client.setex(
                    key,
                    expire,
                    token,
                )

            except Exception:

                pass

    # ======================
    # 消息发送（主动回复）
    # ======================

    def send_text_message(
            self,
            user_id: str,
            content: str
    ) -> dict:

        token = self.get_access_token()

        response = requests.post(
            f"{_BASE}/message/send",
            params={"access_token": token},
            json={
                "touser": user_id,
                "msgtype": "text",
                "agentid": int(settings.wechat_agent_id),
                "text": {"content": content},
            },
            timeout=10,
        )

        return response.json()

    # ======================
    # 用户资料（自动建号用）
    # ======================

    def get_user_info(
            self,
            user_id: str
    ) -> dict:

        token = self.get_access_token()

        response = requests.get(
            f"{_BASE}/user/get",
            params={
                "access_token": token,
                "userid": user_id,
            },
            timeout=10,
        )

        return response.json()


wecom_client = WeComClient()
