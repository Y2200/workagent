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


    return {

        "user": user,

        "content": content

    }