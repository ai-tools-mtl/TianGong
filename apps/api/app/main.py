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
    # 恢复扫描：重启后重入队崩溃中断的解析任务（设计 P0 #6）
    try:
        from app.services.parse_service import recover_pending_jobs

        n = recover_pending_jobs()
        if n:
            loguru.logger.info(f"恢复扫描：重新入队 {n} 个解析任务")
    except Exception as e:
        loguru.logger.exception(f"恢复扫描失败（不阻塞启动）：{e}")

    # 网页摄入任务恢复（异步 spawn，不阻塞 startup；crawl 轮询可能跑数小时）
    try:
        from app.services.web_ingestion_service import recover_pending_jobs as recover_web

        n_web = recover_web()
        if n_web:
            loguru.logger.info(f"恢复扫描：重新入队 {n_web} 个网页摄入任务")
    except Exception as e:
        loguru.logger.exception(f"网页摄入恢复扫描失败（不阻塞启动）：{e}")
