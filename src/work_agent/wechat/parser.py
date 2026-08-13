"""
企业微信XML解析
"""


from xml.etree import ElementTree


def parse_wechat_xml(
    xml_data: str
) -> dict:
    """
    XML转消息对象
    """

    root = ElementTree.fromstring(
        xml_data
    )


    user = root.findtext(
        "FromUserName",
        ""
    )

    content = root.findtext(
        "Content",
        ""
    )

    msg_type = root.findtext(
        "MsgType",
        ""
    )

    msg_id = root.findtext(
        "MsgId",
        ""
    )

    create_time = root.findtext(
        "CreateTime",
        ""
    )


    return {

        "user": user,

        "content": content,

        "msg_type": msg_type,

        "msg_id": msg_id,

        "create_time": create_time,

    }