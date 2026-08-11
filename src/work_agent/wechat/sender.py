"""
企业微信消息发送模块

负责：
1. 获取access_token
2. 发送应用消息
"""


import requests

from work_agent.config import settings



def get_access_token():

    url = (
        "https://qyapi.weixin.qq.com/"
        "cgi-bin/gettoken"
    )


    params = {

        "corpid":
            settings.wechat_corp_id,

        "corpsecret":
            settings.wechat_secret
    }


    response = requests.get(
        url,
        params=params
    )


    data = response.json()


    if data.get("errcode") != 0:
        raise Exception(
            f"获取access_token失败:{data}"
        )


    return data["access_token"]




def send_text_message(
        user_id:str,
        content:str
):

    token = get_access_token()


    url = (
        "https://qyapi.weixin.qq.com/"
        "cgi-bin/message/send"
    )


    params = {

        "access_token":
            token
    }


    body = {

        "touser":
            user_id,


        "msgtype":
            "text",


        "agentid":
            settings.wechat_agent_id,


        "text":
        {
            "content":
                content
        }
    }


    response = requests.post(
        url,
        params=params,
        json=body
    )


    return response.json()