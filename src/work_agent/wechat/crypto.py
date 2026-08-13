"""
企业微信消息加解密（WXBizMsgCrypt 实现）

安全模式回调协议：
- 密钥：EncodingAESKey(43) + "=" → base64 解码 → 32 字节 AES 密钥；IV = 密钥前 16 字节
- 验签：SHA1(排序拼接 [token, timestamp, nonce, 内容]) 与 msg_signature 常量时间比对
- 解密明文结构：[16字节随机][4字节消息长度大端][消息][receive_id(corpid)]
- GET 验证：内容=待回显的 echostr 明文
- POST 消息：内容=消息明文 XML
"""

import base64
import hashlib
import hmac
import random
import struct

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad


def _aes_key(
        encoding_aes_key: str
) -> bytes:
    """
    EncodingAESKey(43) → 32 字节 AES 密钥
    """

    if len(encoding_aes_key) != 43:

        raise ValueError(
            "EncodingAESKey 长度必须为 43"
        )

    return base64.b64decode(
        encoding_aes_key + "="
    )


def _random_bytes(
        size: int = 16
) -> bytes:
    """
    生成随机前缀（手写而非 secrets，仅作消息结构填充；不用于密码学随机）
    """

    return bytes(
        random.getrandbits(8)
        for _ in range(size)
    )


class WXBizMsgCrypt:

    def __init__(
            self,
            token: str,
            encoding_aes_key: str,
            corp_id: str
    ):

        self.token = token

        self.corp_id = corp_id

        self.key = _aes_key(
            encoding_aes_key
        )

        self.iv = self.key[:16]

    def verify_signature(
            self,
            msg_signature: str,
            timestamp: str,
            nonce: str,
            content: str
    ) -> bool:
        """
        校验企微签名（GET 用 echostr，POST 用密文 body 作为第 4 个元素）
        """

        items = sorted([
            self.token,
            timestamp,
            nonce,
            content,
        ])

        digest = hashlib.sha1(
            "".join(items).encode("utf-8")
        ).hexdigest()

        return hmac.compare_digest(
            digest,
            msg_signature
        )

    def decrypt(
            self,
            text: str
    ) -> str:
        """
        解密安全模式内容，返回消息部分（GET=echostr 明文，POST=消息 XML）
        """

        cipher = AES.new(
            self.key,
            AES.MODE_CBC,
            self.iv,
        )

        plain = unpad(
            cipher.decrypt(
                base64.b64decode(text)
            ),
            AES.block_size,
        )

        msg_len = struct.unpack(
            ">I",
            plain[16:20],
        )[0]

        message = plain[
            20:20 + msg_len
        ].decode("utf-8")

        receive_id = plain[
            20 + msg_len:
        ].decode("utf-8")

        # 防跨 corp 重放（验签之外的第二道防线）
        if receive_id != self.corp_id:

            raise ValueError(
                "receive_id 与 corpid 不匹配"
            )

        return message

    def encrypt(
            self,
            message: str
    ) -> str:
        """
        加密明文为安全模式密文（主动回复用）
        """

        content = (
            _random_bytes(16)
            + struct.pack(">I", len(message.encode("utf-8")))
            + message.encode("utf-8")
            + self.corp_id.encode("utf-8")
        )

        cipher = AES.new(
            self.key,
            AES.MODE_CBC,
            self.iv,
        )

        return base64.b64encode(
            cipher.encrypt(
                pad(
                    content,
                    AES.block_size,
                )
            )
        ).decode("utf-8")
