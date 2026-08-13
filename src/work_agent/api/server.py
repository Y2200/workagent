from fastapi import FastAPI, Request
from datetime import datetime

from work_agent.config import settings
from work_agent.wechat.service import process_message


app = FastAPI(
    title="Enterprise Work Agent",
    version="0.1.0"
)



@app.get("/")
async def root():

    return {
        "service":"work-agent",
        "status":"running",
        "time":datetime.now()
    }



@app.get("/health")
async def health():

    return {
        "status":"ok"
    }



@app.get("/config-test")
async def config_test():

    return {
        "corp_id":settings.wechat_corp_id,
        "redis":settings.redis_url,
        "knowledge":settings.knowledge_path
    }



# 企业微信URL验证
@app.get("/wechat/message")
async def wechat_verify(
    msg_signature:str,
    timestamp:str,
    nonce:str,
    echostr:str
):

    return verify_signature(
        msg_signature,
        timestamp,
        nonce,
        echostr
    )



# 企业微信消息
@app.post("/wechat/message")
async def wechat_message(message:dict):

    result = process_message(message)

    return result