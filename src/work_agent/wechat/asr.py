"""
阿里云 NLS 一句话识别（企微语音 → 文本）

流程：
  1. GetToken（AccessKey 签名，缓存 24h）
  2. amr → wav（ffmpeg，16k mono）
  3. POST nls-gateway 一句话识别 → 文本

纯 requests 实现（不引阿里云 SDK）；依赖系统 ffmpeg。
失败返回空串，由调用方给用户友好提示。
"""

import base64
import hashlib
import hmac
import logging
import os
import subprocess
import tempfile
import time
import urllib.parse
import uuid

import requests

from work_agent.config import settings


logger = logging.getLogger(__name__)


def _pct_encode(value) -> str:

    """
    RFC 3986 百分号编码（阿里云签名要求：字母数字 _-~ 不编码，空格 %20）
    """

    return urllib.parse.quote(
        str(value),
        safe="~",
    )


class AlibabaASR:

    def __init__(
            self
    ):

        self._token = ""

        self._token_expire = 0.0


    # ======================
    # 对外接口
    # ======================

    def transcribe_media(
            self,
            media_id: str
    ) -> str:

        """
        下载企微语音媒体 → 转 wav → 识别 → 文本（失败返回空串）
        """

        from work_agent.wechat.client import wecom_client

        audio = wecom_client.get_media(media_id)

        if not audio:

            return ""

        return self.transcribe_audio(audio)


    def transcribe_audio(
            self,
            audio: bytes
    ) -> str:

        """
        音频字节 → 文本（内部：amr→wav → token → 识别）
        """

        if not audio:

            return ""

        wav = self._to_wav(audio)

        if not wav:

            return ""

        token = self._get_token()

        if not token:

            return ""

        return self._recognize(wav, token)


    # ======================
    # amr → wav（ffmpeg）
    # ======================

    def _to_wav(
            self,
            audio: bytes
    ) -> bytes:

        with tempfile.TemporaryDirectory() as tmp:

            src = os.path.join(tmp, "in.amr")

            dst = os.path.join(tmp, "out.wav")

            with open(src, "wb") as fh:

                fh.write(audio)

            try:

                result = subprocess.run(
                    [
                        "ffmpeg", "-y", "-i", src,
                        "-ar", str(settings.asr_sample_rate),
                        "-ac", "1", "-f", "wav", dst,
                    ],
                    capture_output=True,
                    timeout=30,
                )

            except FileNotFoundError:

                raise RuntimeError(
                    "缺少 ffmpeg，无法转换语音格式（部署需安装 ffmpeg）"
                )

            except subprocess.TimeoutExpired:

                logger.error("ffmpeg 转 wav 超时")

                return b""

            if result.returncode != 0:

                logger.error(
                    "ffmpeg 转 wav 失败: %s",
                    (result.stderr or b"")[-500:],
                )

                return b""

            with open(dst, "rb") as fh:

                return fh.read()


    # ======================
    # GetToken（阿里云 RPC 签名）
    # ======================

    def _get_token(
            self
    ) -> str:

        if (
            self._token
            and self._token_expire > time.time() + 300
        ):

            return self._token

        try:

            token = self._fetch_token()

        except Exception:

            logger.exception("获取 NLS token 失败")

            return ""

        self._token = token.get(
            "Id",
            "",
        )

        self._token_expire = float(
            token.get(
                "ExpireTime",
                0,
            ) or 0
        )

        return self._token


    def _fetch_token(
            self
    ) -> dict:

        region = settings.asr_region

        params = {
            "AccessKeyId": settings.aliyun_access_key_id,
            "Action": "GetToken",
            "Format": "JSON",
            "RegionId": region,
            "SignatureMethod": "HMAC-SHA1",
            "SignatureNonce": str(uuid.uuid4()),
            "SignatureVersion": "1.0",
            "Timestamp": time.strftime(
                "%Y-%m-%dT%H:%M:%SZ",
                time.gmtime(),
            ),
            "Version": "2019-02-28",
        }

        signature = self._sign(
            params,
            settings.aliyun_access_key_secret,
        )

        params["Signature"] = signature

        query = "&".join(
            f"{_pct_encode(k)}={_pct_encode(str(v))}"
            for k, v in params.items()
        )

        url = (
            f"https://nls-meta.{region}.aliyuncs.com"
            f"/api/v2/ws/token?{query}"
        )

        response = requests.get(
            url,
            timeout=10,
        )

        data = response.json()

        if not data.get("Token"):

            logger.error(
                "NLS GetToken 失败: %s",
                data,
            )

            raise RuntimeError(
                f"获取语音识别令牌失败: {data}"
            )

        return data["Token"]


    @staticmethod
    def _sign(
            params: dict,
            secret: str
    ) -> str:

        """
        阿里云 RPC V1 签名（HMAC-SHA1）
        """

        canonical = "&".join(
            f"{_pct_encode(k)}={_pct_encode(str(v))}"
            for k, v in sorted(params.items())
        )

        string_to_sign = (
            "GET&%2F&"
            + _pct_encode(canonical)
        )

        key = (
            secret + "&"
        ).encode("utf-8")

        digest = hmac.new(
            key,
            string_to_sign.encode("utf-8"),
            hashlib.sha1,
        ).digest()

        return base64.b64encode(
            digest
        ).decode("utf-8")


    # ======================
    # 一句话识别
    # ======================

    def _recognize(
            self,
            wav: bytes,
            token: str
    ) -> str:

        region = settings.asr_region

        url = (
            f"https://nls-gateway-{region}.aliyuncs.com"
            f"/stream/v1/asr"
        )

        params = {
            "appkey": settings.aliyun_nls_appkey,
            "format": "wav",
            "sample_rate": settings.asr_sample_rate,
            "enable_intermediate_result": "false",
            "enable_punctuation_prediction": "true",
            "enable_inverse_text_normalization": "true",
        }

        headers = {
            "X-NLS-Token": token,
            "Content-Type": "audio/wav",
        }

        try:

            response = requests.post(
                url,
                params=params,
                headers=headers,
                data=wav,
                timeout=60,
            )

        except Exception:

            logger.exception("一句话识别请求异常")

            return ""

        try:

            data = response.json()

        except ValueError:

            logger.error(
                "一句话识别响应非 JSON: %s",
                response.text[:200],
            )

            return ""

        if data.get("status") != 20000000:

            logger.error(
                "一句话识别失败: %s",
                data,
            )

            return ""

        return (
            data.get("result")
            or ""
        ).strip()


asr_service = AlibabaASR()
