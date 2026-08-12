import sys

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from datetime import datetime

from work_agent.config import settings
from work_agent.core.exceptions import TenantAccessDenied


# Windows 控制台/管道默认 GBK 编码，agent 节点 print() 可能触发
# UnicodeEncodeError。统一重配置为 UTF-8，避免请求运行时崩溃。
if hasattr(sys.stdout, "reconfigure"):

    sys.stdout.reconfigure(
        encoding="utf-8",
        errors="replace"
    )

    sys.stderr.reconfigure(
        encoding="utf-8",
        errors="replace"
    )

from fastapi import Request

from work_agent.wechat.service import process_message
from work_agent.wechat.parser import parse_wechat_xml
from work_agent.wechat.verify import verify_signature
from work_agent.api.admin import router as admin_router
from work_agent.api.knowledge_intelligence import router as knowledge_intelligence_router
from work_agent.api.trace import router as trace_router
from work_agent.api.config import router as config_router
from work_agent.api.prompt import router as prompt_router
from work_agent.api.cost import router as cost_router
from work_agent.api.resilience import router as resilience_router


app = FastAPI(
    title="Enterprise Work Agent",
    version="0.1.0"
)


app.include_router(
    admin_router
)

app.include_router(
    knowledge_intelligence_router
)

app.include_router(
    trace_router
)

app.include_router(
    config_router
)

app.include_router(
    prompt_router
)

app.include_router(
    cost_router
)

app.include_router(
    resilience_router
)


# Web 前端跨域（开发环境放行所有来源，生产由 nginx 同源代理）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(TenantAccessDenied)
async def tenant_access_denied_handler(
        request: Request,
        exc: TenantAccessDenied
):

    """
    跨租户越权统一返回 403
    """

    return JSONResponse(
        status_code=403,
        content={
            "detail": str(exc)
        }
    )


@app.get("/")
async def root():
    return {
        "service": "work-agent",
        "status": "running",
        "time": datetime.now()
    }


@app.get("/health")
async def health():
    return {
        "status": "ok"
    }


@app.get("/config-test")
async def config_test():
    return {
        "corp_id": settings.wechat_corp_id,
        "redis": settings.redis_url,
        "knowledge": settings.knowledge_path
    }


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



@app.post("/wechat/message")
async def wechat_message(
        request:Request
):

    body = await request.body()

    xml_data = body.decode(
        "utf-8",
        errors="ignore"
    )


    message = parse_wechat_xml(
        xml_data
    )


    result = process_message(
        message
    )


    return result