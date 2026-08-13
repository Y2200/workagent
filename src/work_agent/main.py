import logging
import sys

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from datetime import datetime

from work_agent.config import settings
from work_agent.core.exceptions import TenantAccessDenied


# 生产/排障日志：INFO 级输出到 stdout（docker logs 可见）
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


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

from work_agent.api.admin import router as admin_router
from work_agent.api.knowledge_intelligence import router as knowledge_intelligence_router
from work_agent.api.trace import router as trace_router
from work_agent.api.config import router as config_router
from work_agent.api.prompt import router as prompt_router
from work_agent.api.cost import router as cost_router
from work_agent.api.resilience import router as resilience_router
from work_agent.api.health import router as health_router
from work_agent.api.wechat import router as wechat_router
from work_agent.api.users import router as users_router


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

app.include_router(
    health_router
)

app.include_router(
    wechat_router
)

app.include_router(
    users_router
)


# Web 前端跨域
# 开发：cors_origins 留空 → 放行所有来源（宽松）
# 生产：cors_origins=https://wkcp.online → 仅允许前端来源
_cors_origins = [
    origin.strip()
    for origin in settings.cors_origins.split(",")
    if origin.strip()
] or ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
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