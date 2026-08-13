"""
企业微信（WeCom）接入测试套件

Part A  加解密（无外部依赖）：WXBizMsgCrypt 官方向量 / 往返 / 防篡改 / 跨corp / key长度
Part B  XML 解析（无外部依赖）：user/content/msg_type/msg_id
Part C  回调路由（无需 Milvus）：验签 / 解密 / 明文模式 / 非text / 幂等去重
Part D  用户绑定 API（需 Postgres + Milvus，依赖不可用则跳过）

用法：
    python -m work_agent.scripts.test_wecom
"""

import hashlib

from fastapi import FastAPI
from fastapi.testclient import TestClient

from work_agent.config import settings
from work_agent.wechat.crypto import WXBizMsgCrypt
from work_agent.wechat.parser import parse_wechat_xml


# 企业微信官方示例向量
TOKEN = "QDG6eK"

AES_KEY = "abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG"

CORP_ID = "wx5823bf96d3bd56c7"


def _sign(
        token: str,
        timestamp: str,
        nonce: str,
        content: str
) -> str:

    return hashlib.sha1(
        "".join(
            sorted([token, timestamp, nonce, content])
        ).encode("utf-8")
    ).hexdigest()


# ======================
# Part A 加解密
# ======================

def test_crypto():

    crypto = WXBizMsgCrypt(
        TOKEN,
        AES_KEY,
        CORP_ID,
    )

    xml = (
        "<xml><ToUserName>wx5823bf96d3bd56c7</ToUserName>"
        "<Content>你好</Content></xml>"
    )

    # 官方向量加解密往返
    enc = crypto.encrypt(xml)

    assert crypto.decrypt(enc) == xml

    # 验签通过 / 篡改拒绝
    timestamp, nonce = "1409659589", "263014780"

    assert crypto.verify_signature(
        _sign(TOKEN, timestamp, nonce, enc),
        timestamp,
        nonce,
        enc,
    ) is True

    assert crypto.verify_signature(
        "x" * 40,
        timestamp,
        nonce,
        enc,
    ) is False

    # 跨 corp 拒绝
    other = WXBizMsgCrypt(
        TOKEN,
        AES_KEY,
        "othercorp",
    )

    try:

        other.decrypt(enc)

        raise AssertionError(
            "跨 corp 解密应当失败"
        )

    except ValueError:

        pass

    # key 长度校验
    try:

        WXBizMsgCrypt(
            TOKEN,
            "short",
            CORP_ID,
        )

        raise AssertionError(
            "非法 key 长度应当报错"
        )

    except ValueError:

        pass

    print(
        "Part A ✅ 加解密（官方向量/往返/验签/防篡改/跨corp/key长度）"
    )


# ======================
# Part B XML 解析
# ======================

def test_parser():

    msg = parse_wechat_xml(
        "<xml>"
        "<FromUserName>zhangsan</FromUserName>"
        "<Content>你好</Content>"
        "<MsgType>text</MsgType>"
        "<MsgId>1001</MsgId>"
        "</xml>"
    )

    assert msg["user"] == "zhangsan"

    assert msg["content"] == "你好"

    assert msg["msg_type"] == "text"

    assert msg["msg_id"] == "1001"

    print(
        "Part B ✅ XML 解析（user/content/msg_type/msg_id）"
    )


# ======================
# Part C 回调路由（迷你 app，规避 Milvus）
# ======================

def _make_callback_env():

    import work_agent.api.wechat as aw

    app = FastAPI()

    app.include_router(aw.router)

    return app, aw


def test_callback():

    saved = (
        settings.wechat_token,
        settings.wechat_encoding_aes_key,
        settings.wechat_corp_id,
    )

    settings.wechat_token = TOKEN

    settings.wechat_encoding_aes_key = AES_KEY

    settings.wechat_corp_id = CORP_ID

    try:

        app, aw = _make_callback_env()

        crypto = WXBizMsgCrypt(
            TOKEN,
            AES_KEY,
            CORP_ID,
        )

        calls = []

        def fake_process(
                msg: dict
        ) -> dict:

            calls.append(("process", msg))

            return {
                "response": "测试回复"
            }

        class FakeClient:

            def send_text_message(
                    self,
                    user_id,
                    content,
            ):

                calls.append((
                    "send",
                    user_id,
                    content,
                ))

                return {
                    "errcode": 0
                }

        aw.process_message = fake_process

        aw.wecom_client = FakeClient()

        client = TestClient(app)

        # 1) GET 安全模式验证：验签 + 解密回显
        timestamp, nonce = "111", "222"

        echo_plain = "verifycode123"

        enc_echo = crypto.encrypt(echo_plain)

        resp = client.get(
            "/api/wechat/callback",
            params={
                "msg_signature": _sign(
                    TOKEN,
                    timestamp,
                    nonce,
                    enc_echo,
                ),
                "timestamp": timestamp,
                "nonce": nonce,
                "echostr": enc_echo,
            },
        )

        assert resp.status_code == 200

        assert resp.text == echo_plain, resp.text

        # 2) GET 明文模式：无签名直接回显
        resp = client.get(
            "/api/wechat/callback",
            params={"echostr": "plain"},
        )

        assert resp.text == "plain"

        # 3) GET 签名错误 → 空
        resp = client.get(
            "/api/wechat/callback",
            params={
                "msg_signature": "bad",
                "timestamp": timestamp,
                "nonce": nonce,
                "echostr": enc_echo,
            },
        )

        assert resp.text == ""

        # 4) POST 安全模式有效文本消息 → 后台执行并主动回复
        xml = (
            f"<xml><ToUserName>{CORP_ID}</ToUserName>"
            "<FromUserName>zhangsan</FromUserName>"
            "<CreateTime>123</CreateTime>"
            "<MsgType>text</MsgType>"
            "<Content>报销制度</Content>"
            "<MsgId>9001</MsgId></xml>"
        )

        enc = crypto.encrypt(xml)

        timestamp, nonce = "333", "444"

        resp = client.post(
            "/api/wechat/callback",
            params={
                "msg_signature": _sign(
                    TOKEN,
                    timestamp,
                    nonce,
                    enc,
                ),
                "timestamp": timestamp,
                "nonce": nonce,
            },
            content=enc,
        )

        assert resp.status_code == 200

        assert resp.text == ""

        assert (
            "send",
            "zhangsan",
            "测试回复",
        ) in calls, calls

        # 5) POST 签名错误 → 空且不处理
        resp = client.post(
            "/api/wechat/callback",
            params={
                "msg_signature": "bad",
                "timestamp": timestamp,
                "nonce": nonce,
            },
            content=enc,
        )

        assert resp.text == ""

        send_count = sum(
            1
            for c in calls
            if c == ("send", "zhangsan", "测试回复")
        )

        assert send_count == 1, calls

        # 6) POST 非 text 消息 → 忽略
        xml_event = (
            "<xml><MsgType>event</MsgType>"
            "<FromUserName>zhangsan</FromUserName>"
            "<Content></Content></xml>"
        )

        enc_event = crypto.encrypt(xml_event)

        n_before = len(calls)

        resp = client.post(
            "/api/wechat/callback",
            params={
                "msg_signature": _sign(
                    TOKEN,
                    "555",
                    "666",
                    enc_event,
                ),
                "timestamp": "555",
                "nonce": "666",
            },
            content=enc_event,
        )

        assert resp.text == ""

        assert len(calls) == n_before

        # 7) 幂等去重：同一 MsgId 第二次被拦截
        seen = set()

        def dedup(
                msg_id: str
        ) -> bool:

            if msg_id in seen:

                return False

            seen.add(msg_id)

            return True

        aw._dedup = dedup

        xml2 = (
            f"<xml><ToUserName>{CORP_ID}</ToUserName>"
            "<FromUserName>lisi</FromUserName>"
            "<MsgType>text</MsgType>"
            "<Content>制度查询</Content>"
            "<MsgId>9100</MsgId></xml>"
        )

        enc2 = crypto.encrypt(xml2)

        timestamp, nonce = "777", "888"

        resp1 = client.post(
            "/api/wechat/callback",
            params={
                "msg_signature": _sign(
                    TOKEN,
                    timestamp,
                    nonce,
                    enc2,
                ),
                "timestamp": timestamp,
                "nonce": nonce,
            },
            content=enc2,
        )

        assert resp1.status_code == 200

        n_after_first = len(calls)

        resp2 = client.post(
            "/api/wechat/callback",
            params={
                "msg_signature": _sign(
                    TOKEN,
                    timestamp,
                    nonce,
                    enc2,
                ),
                "timestamp": timestamp,
                "nonce": nonce,
            },
            content=enc2,
        )

        assert resp2.text == ""

        assert len(calls) == n_after_first, calls

        # 8) 未配置 token/key → 一律返回空
        settings.wechat_token = ""

        resp = client.post(
            "/api/wechat/callback",
            content=enc,
        )

        assert resp.text == ""

        settings.wechat_token = TOKEN

        print(
            "Part C ✅ 回调路由（验签/解密/明文/非text/幂等/未配置）"
        )

    finally:

        (
            settings.wechat_token,
            settings.wechat_encoding_aes_key,
            settings.wechat_corp_id,
        ) = saved


# ======================
# Part D 用户绑定 API（需 Postgres + Milvus）
# ======================

def test_user_binding():

    try:

        from work_agent.main import app

    except Exception as exc:

        print(
            f"Part D ⏭️ 跳过（依赖不可用: {exc}）"
        )

        return

    from work_agent.scripts.seed_rbac import seed_rbac

    seed_rbac()

    client = TestClient(app)

    def login(
            username: str
    ) -> dict:

        resp = client.post(
            "/api/admin/auth/login",
            json={
                "username": username,
                "password": "test123",
            },
        )

        assert resp.status_code == 200, resp.text

        return {
            "Authorization":
                f"Bearer {resp.json()['access_token']}"
        }

    admin_a = login("admin_A")

    admin_b = login("admin_B")

    # 1) 列表：租户管理员仅本租户
    resp = client.get(
        "/api/admin/users",
        headers=admin_a,
    )

    assert resp.status_code == 200, resp.text

    users = resp.json()["items"]

    assert all(
        u["tenant_id"] == "1"
        for u in users
    ), users

    target = next(
        u
        for u in users
        if u["username"] == "A财务员工"
    )

    other = next(
        u
        for u in users
        if u["username"] != "A财务员工"
    )

    # 2) 绑定
    resp = client.put(
        f"/api/admin/users/{target['id']}/wechat",
        headers=admin_a,
        json={"wechat_user_id": "wx_bind_test"},
    )

    assert resp.status_code == 200, resp.text

    assert resp.json()["wechat_user_id"] == "wx_bind_test"

    # 3) 冲突：同一企微账号已绑定他人 → 409
    resp = client.put(
        f"/api/admin/users/{other['id']}/wechat",
        headers=admin_a,
        json={"wechat_user_id": "wx_bind_test"},
    )

    assert resp.status_code == 409, resp.text

    # 4) 解绑
    resp = client.delete(
        f"/api/admin/users/{target['id']}/wechat",
        headers=admin_a,
    )

    assert resp.status_code == 200, resp.text

    assert resp.json()["wechat_user_id"] is None

    # 5) 跨租户：admin_B 无权管理 admin_A 租户用户 → 403
    resp = client.put(
        f"/api/admin/users/{target['id']}/wechat",
        headers=admin_b,
        json={"wechat_user_id": "x"},
    )

    assert resp.status_code == 403, resp.text

    # 6) 普通用户无 user:manage → 403
    user_headers = login("A财务员工")

    resp = client.get(
        "/api/admin/users",
        headers=user_headers,
    )

    assert resp.status_code == 403, resp.text

    # 还原绑定，避免影响其他测试
    client.put(
        f"/api/admin/users/{target['id']}/wechat",
        headers=admin_a,
        json={"wechat_user_id": "wx_A_finance"},
    )

    print(
        "Part D ✅ 用户绑定 API（列表/绑定/冲突/解绑/越权）"
    )


def test():

    test_crypto()

    test_parser()

    test_callback()

    test_user_binding()


if __name__ == "__main__":

    test()
