"""
消息数据清洗模块

负责：
1. 去除无效消息
2. 标准化字段
3. 给Agent提供统一输入
"""


from datetime import datetime



def clean_message(message: dict) -> dict:
    """
    清洗企业微信消息
    """


    user = message.get(
        "user",
        ""
    )

    department = message.get(
        "department",
        "未知"
    )

    role = message.get(
        "role",
        "员工"
    )


    content = message.get(
        "content",
        ""
    )


    # 去空格

    user = user.strip()

    content = content.strip()



    if not user:
        raise ValueError(
            "用户不能为空"
        )


    if not content:
        raise ValueError(
            "消息内容不能为空"
        )



    return {

        "user":
            user,


        "department":
            department,


        "role":
            role,


        "content":
            content,


        "timestamp":
            datetime.now().isoformat()

    }