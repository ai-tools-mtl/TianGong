import loguru
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers

settings = get_settings()

app = FastAPI(
    title="TianGong API",
    description="AI 驱动的专利交底书撰写智能体",
    version="0.1.0",
)

# CORS（前端跨域）
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,  # cookie 跨域必需
    allow_methods=["*"],
    allow_headers=["*"],
)

# 全局异常处理
register_exception_handlers(app)

# 路由
app.include_router(api_router)


@app.on_event("startup")
def on_startup():
    loguru.logger.info("TianGong API 启动")
