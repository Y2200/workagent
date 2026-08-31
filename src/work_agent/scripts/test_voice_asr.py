"""
企微语音识别测试（阿里云 ASR 接入）

Part 1a asr_service：RPC 签名生成
Part 1b 一句话识别（mock requests：URL/头/成功/失败）
Part 2  语音消息 → ASR → 文本 → 流入 Runtime（mock 下载/转写/agent）
Part 3  ASR 未开启 → 明确提示

用法：
    python -m work_agent.scripts.test_voice_asr
"""

from unittest import mock

from work_agent.config import settings
from work_agent.scripts.seed_tenants import seed_tenants
from work_agent.wechat.asr import AlibabaASR, asr_service

import work_agent.wechat.service as ws


def _sign_test():

    """Part 1a：RPC 签名生成（格式校验）"""

    params = {
        "AccessKeyId": "LTAI",
        "Action": "GetToken",
        "Format": "JSON",
        "RegionId": "cn-shanghai",
        "SignatureMethod": "HMAC-SHA1",
        "SignatureNonce": "nonce-1",
        "SignatureVersion": "1.0",
        "Timestamp": "2026-08-31T00:00:00Z",
        "Version": "2019-02-28",
    }

    sig = AlibabaASR._sign(
        params,
        "test-secret",
    )

    assert isinstance(sig, str) and len(sig) > 10, sig

    # 确定性：同参数同签名
    sig2 = AlibabaASR._sign(
        params,
        "test-secret",
    )

    assert sig == sig2, "签名应确定性"

    print("✓ Part1a RPC 签名生成（确定性）")


def _recognize_test():

    """Part 1b：一句话识别（mock requests）"""

    asr = AlibabaASR()

    with mock.patch(
        "requests.post",
    ) as mp:

        mp.return_value.json.return_value = {
            "status": 20000000,
            "result": "给张三安排任务",
        }

        text = asr._recognize(
            b"WAVDATA",
            "token123",
        )

        assert text == "给张三安排任务", text

        args = mp.call_args

        # 请求 URL 指向 nls-gateway + region
        assert "nls-gateway" in args[0][0], args[0][0]

        assert "cn-shanghai" in args[0][0], args[0][0]

        assert (
            args[1]["headers"]["X-NLS-Token"] == "token123"
        ), args[1]

        # 失败 status → 空串
        mp.return_value.json.return_value = {
            "status": 40000000,
            "message": "识别失败",
        }

        assert asr._recognize(
            b"WAV",
            "token123",
        ) == ""

    print("✓ Part1b 一句话识别（URL/头/成功/失败）")


def _transcribe_voice_test():

    """Part 2：语音消息 → ASR → 文本 → 流入 Runtime"""

    seed_tenants()

    saved = settings.asr_enabled

    settings.asr_enabled = True

    try:

        with mock.patch.object(
            ws,
            "agent_runtime",
        ) as mr:

            mr.execute.return_value = {
                "response": "语音已回答",
                "intent": "knowledge_query",
            }

            with mock.patch(
                "work_agent.wechat.client.wecom_client.get_media",
            ) as mg:

                mg.return_value = b"fake-amr-bytes"

                with mock.patch.object(
                    asr_service,
                    "transcribe_audio",
                ) as mta:

                    mta.return_value = "给张三安排任务"

                    result = ws.process_message({
                        "user": "wx_A_dev",
                        "msg_type": "voice",
                        "media_id": "media-1",
                        "content": "",
                    })

        assert result["response"] == "语音已回答", result

        assert mr.execute.call_count == 1, mr.execute.call_count

        # Runtime 收到的 message = ASR 转写文本
        called = mr.execute.call_args.kwargs.get(
            "message",
        )

        assert called == "给张三安排任务", called

    finally:

        settings.asr_enabled = saved

    print("✓ Part2 语音消息 → ASR → 文本 → Runtime")


def _disabled_test():

    """Part 3：ASR 未开启 → 明确提示"""

    saved = settings.asr_enabled

    settings.asr_enabled = False

    try:

        result = ws.process_message({
            "user": "wx_A_dev",
            "msg_type": "voice",
            "media_id": "media-1",
            "content": "",
        })

        assert (
            "语音识别未开启" in result.get("message", "")
        ), result

    finally:

        settings.asr_enabled = saved

    print("✓ Part3 未开启 → 明确提示")


def test():

    print("== 语音识别（企微语音 → 阿里云 ASR）==")

    _sign_test()

    _recognize_test()

    _transcribe_voice_test()

    _disabled_test()

    print("语音识别测试全部通过")


if __name__ == "__main__":

    test()
