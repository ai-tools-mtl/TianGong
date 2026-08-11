import loguru
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import setup_logging
from app.core.middleware import RequestIDMiddleware

settings = get_settings()

# 装配日志系统：必须在 FastAPI 实例化前，否则 uvicorn 的日志来不及被接管。
# 统一 loguru 为单一出口，标准库 logging（含 uvicorn/sqlalchemy/httpx）经
# InterceptHandler 桥接进来。详见 app/core/logging.py。
setup_logging(settings)

app = FastAPI(
    title="TianGong API",
    description="AI 驱动的专利交底书撰写智能体",
    version="0.1.0",
)

# request-id 中间件：最先注册（Starlette 后进先出，实际最外层执行），
# 确保所有后续中间件/路由都在 request_id 上下文内。
app.add_middleware(RequestIDMiddleware)

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

# P0-5：速率限制（slowapi）——登录/注册/AI 调用等敏感端点
from app.core.rate_limit import register_rate_limit
register_rate_limit(app)

# 路由
app.include_router(api_router)


@app.on_event("startup")
def on_startup():
    import os
    loguru.logger.info("TianGong API 启动")

    # 预检（embedding 维度 / rerank 连通性）连真实推理微服务，测试环境没有。
    # TIANGONG_TESTING=1 时跳过，避免每个 client fixture 触发 startup 时的网络超时累加。
    _skip_preflight = os.environ.get("TIANGONG_TESTING") == "1"

    # embedding 维度一致性断言（P3-12）：启动时探测一次，维度不匹配 fail fast
    # 而非等到第一次真实写入才在 DB 报 DataException。embedding 服务未起时降级 warning。
    if not _skip_preflight:
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
                else:
                    loguru.logger.info(
                        f"embedding 服务连通正常（{cfg.base_url}，模型 {cfg.model}，输出 {len(vec)} 维）"
                    )
        except Exception as e:
            loguru.logger.warning(f"embedding 维度探测失败（不阻塞启动）：{e}")

        # rerank 连通性探测（与 embedding 维度探测同级）：rerank_enabled=True 才探测。
        # 服务未起或返回异常 → warning 不阻塞（rerank 是 fail-open，检索会降级原序）；
        # 目的是让运维从启动日志第一时间发现 rerank 没生效，而非靠检索变慢才发现。
        try:
            from app.services.rag_config_service import resolve_rerank_config
            import httpx

            rerank_cfg = resolve_rerank_config()
            if rerank_cfg.enabled:
                health_url = rerank_cfg.base_url.rstrip("/") + "/health"
                r = httpx.get(health_url, timeout=3.0)
                if r.status_code < 500:
                    loguru.logger.info(
                        f"rerank 服务连通正常（{rerank_cfg.base_url}，模型 {rerank_cfg.model}）"
                    )
                else:
                    loguru.logger.warning(
                        f"⚠️ rerank 服务返回 {r.status_code}（{rerank_cfg.base_url}），"
                        f"检索将走 fail-open 原序降级"
                    )
            else:
                loguru.logger.info("rerank 已关闭（RERANK_ENABLED=false），检索不走精排")
        except Exception as e:
            loguru.logger.warning(
                f"rerank 服务连通探测失败（不阻塞启动，检索将降级原序）：{e}"
            )

        # Firecrawl 连通性探测(本地自部署):挂了网页摄入不可用,启动时告警让运维第一时间发现。
        # 与 embedding/rerank 探活同级;firecrawl 是软依赖,不可达只 warning 不阻塞启动。
        try:
            from app.services.firecrawl_client import check_firecrawl_health

            fc_base = settings.firecrawl_base_url
            if check_firecrawl_health(fc_base):
                loguru.logger.info(f"Firecrawl 服务连通正常（{fc_base}）")
            else:
                loguru.logger.warning(
                    f"⚠️ Firecrawl 服务不可达（{fc_base}），"
                    f"网页摄入(抓取网页)功能将不可用,用户调用时会报错。请检查 firecrawl 容器状态。"
                )
        except Exception as e:
            loguru.logger.warning(
                f"Firecrawl 服务连通探测失败（不阻塞启动，网页摄入将不可用）：{e}"
            )

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

    # 内置 skill 同步：扫描项目根 assets/skills/，幂等 upsert 进 DB + MinIO
    # （标记 is_builtin=True，scope=global/status=active 自动喂给 agent）。
    # 失败不阻塞启动（MinIO 未起、目录缺失等降级为 warning）。
    try:
        from app.core.database import SessionLocal
        from app.skills.builtin_loader import sync_builtin_skills

        db = SessionLocal()
        try:
            created, updated = sync_builtin_skills(db)
            if created or updated:
                loguru.logger.info(
                    f"内置技能同步：新建 {created}，更新 {updated}"
                )
        finally:
            db.close()
    except Exception as e:
        loguru.logger.exception(f"内置技能同步失败（不阻塞启动）：{e}")
