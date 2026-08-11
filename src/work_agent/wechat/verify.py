"""
企业微信URL验证
"""


def verify_signature(
    signature: str,
    timestamp: str,
    nonce: str,
    echostr: str
):

    print("================")
    print("企业微信验证")
    print("signature:", signature)
    print("timestamp:", timestamp)
    print("nonce:", nonce)
    print("echostr:", echostr)
    print("================")


    # 后续替换真实sha1校验

    return echostr