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
    # embedding 维度一致性断言（P3-12）：启动时探测一次，维度不匹配 fail fast
    # 而非等到第一次真实写入才在 DB 报 DataException。embedding 服务未起时降级 warning。
    try:
        from app.rag.embedding import embed_text
        from app.services.llm_config_service import resolve_embedding_config
        from app.models.knowledge_chunk import EMBEDDING_DIM

        cfg = resolve_embedding_config()
        if cfg is not None:
            vec = embed_text("维度探测", embed_config=cfg)
            if len(vec) != EMBEDDING_DIM:
                loguru.logger.error(
                    f"⚠️ embedding 维度不匹配：模型输出 {len(vec)} 维，"
                    f"但 knowledge_chunks.embedding 列是 {EMBEDDING_DIM} 维。"
                    f"请检查 EMBEDDING_MODEL 配置或跑维度对齐迁移。"
                )
    except Exception as e:
        loguru.logger.warning(f"embedding 维度探测失败（不阻塞启动）：{e}")

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

    # 知识文件向量化恢复（plan async-knowledge-upload：孤儿 pending/processing 重入队）
    try:
        from app.services.knowledge_service import recover_stale_files

        n_kf = recover_stale_files()
        if n_kf:
            loguru.logger.info(f"恢复扫描：重新入队 {n_kf} 个知识文件向量化任务")
    except Exception as e:
        loguru.logger.exception(f"知识文件向量化恢复扫描失败（不阻塞启动）：{e}")

    # 归档向量化恢复（archiving 态孤儿项目重入队）
    try:
        from app.rag.archiver import recover_stale_archives

        n_arc = recover_stale_archives()
        if n_arc:
            loguru.logger.info(f"恢复扫描：重新入队 {n_arc} 个归档向量化任务")
    except Exception as e:
        loguru.logger.exception(f"归档向量化恢复扫描失败（不阻塞启动）：{e}")
