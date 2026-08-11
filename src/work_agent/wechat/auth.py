import requests

from work_agent.config import settings



def get_access_token():

    url = (
        "https://qyapi.weixin.qq.com/cgi-bin/gettoken"
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


    return data