"""管理员：系统控制台域（/admin/llm-config + /admin/stats/* + /admin/audit-logs）。

从原 admin.py 拆出（refactor/admin-api-split）。包含：
- GET  /admin/llm-config         全局 LLM 配置
- PUT  /admin/llm-config         保存全局 LLM 配置（写审计）
- GET  /admin/stats/llm          LLM 调用统计聚合
- GET  /admin/stats/llm/health   LLM 健康摘要（落地页用）
- GET  /admin/stats/users        用户聚合统计
- GET  /admin/audit-logs         审计日志分页
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import decrypt_value
from app.deps import require_admin
from app.models import AuditLog, SystemSetting, User
from app.services import admin_service, llm_config_service, stats_service

router = APIRouter(tags=["admin"])


class GlobalScopeConfigBody(BaseModel):
    """chat 全局配置的 body。embedding 已走固定微服务，不再有全局配置。"""
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = Field(default=None, min_length=1)


class GlobalLLMSettings(BaseModel):
    """admin 设置全局 LLM 配置。只管 chat（embedding 走固定 bge-m3 微服务）。"""
    enabled: bool
    chat_config: GlobalScopeConfigBody | None = None


class LiteConfigBody(BaseModel):
    """轻量任务模型配置 body（独立于 chat 全局配置，承接会话标题/章节摘要）。"""
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = Field(default=None, min_length=1)


class LiteSettings(BaseModel):
    """admin 设置轻量任务模型配置。无 enabled 开关（未配即回退 chat 全局/用户配置）。"""
    lite_config: LiteConfigBody | None = None


class GlobalScopeTestRequest(BaseModel):
    """admin 测试全局 chat（支持传值或用已存值复检）。"""
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None


class ListModelsRequest(BaseModel):
    """拉取 provider 可用模型列表（不落库）。"""
    base_url: str
    api_key: str
    provider_template_id: str | None = None


# ── LLM 调用统计（设计 8.2④，仅元数据聚合）──

@router.get("/admin/stats/llm")
def get_llm_stats_endpoint(
    days: int = 7,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """LLM 调用统计聚合（绝不返回 prompt/completion 内容）。"""
    if days < 1 or days > 90:
        days = 7
    return stats_service.get_llm_stats(db, days=days)


@router.get("/admin/stats/llm/health")
def get_llm_health_endpoint(
    days: int = 7,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """LLM 调用健康摘要（admin 落地页 LLM 健康卡片用）。

    返回 {days, total, failed, failure_rate, status}。阈值由
    stats_service.LLM_HEALTH_FAILURE_THRESHOLD（当前 5%）决定 status=ok/warning。
    """
    if days < 1 or days > 90:
        days = 7
    return stats_service.get_llm_health(db, days=days)


@router.get("/admin/stats/users")
def get_user_stats_endpoint(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """用户聚合统计（仪表盘卡片用：总数/活跃/禁用/新增/有效授权数）。"""
    return stats_service.get_user_stats(db)


# ── 审计日志列表（设计 8.2⑤）──

@router.get("/admin/audit-logs")
def list_audit_logs(
    page: int = 1,
    size: int = 50,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """审计日志列表（分页，时间倒序）。"""
    if page < 1:
        page = 1
    if size < 1 or size > 200:
        size = 50

    total = db.scalar(select(func.count(AuditLog.id))) or 0
    rows = list(db.scalars(
        select(AuditLog)
        .order_by(AuditLog.created_at.desc())
        .offset((page - 1) * size)
        .limit(size)
    ))
    return {
        "total": total,
        "page": page,
        "size": size,
        "items": [
            {
                "id": str(r.id),
                "actor_id": str(r.actor_id) if r.actor_id else None,
                "actor_username": r.actor_username,
                "action": r.action,
                "target_type": r.target_type,
                "target_id": r.target_id,
                "detail": r.detail,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }


# ── 全局 LLM 配置（只管 chat；embedding 走固定 bge-m3 微服务）──

@router.get("/admin/llm-config")
def get_global_llm(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    enabled = db.scalar(select(SystemSetting).where(SystemSetting.key == "llm_global_enabled"))
    return {
        "llm_global_enabled": enabled.value.get("enabled", True) if enabled else True,
        "chat_config": llm_config_service.get_global_chat_settings(db),
    }


@router.put("/admin/llm-config")
def set_global_llm(
    payload: GlobalLLMSettings,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if payload.chat_config:
        c = payload.chat_config
        llm_config_service.set_global_chat_settings(
            db, enabled=payload.enabled,
            base_url=c.base_url, api_key=c.api_key, model=c.model,
        )
    else:
        # 没传 chat_config 也要更新 enabled 开关（set_global_chat_settings 会写 enabled）
        llm_config_service.set_global_chat_settings(db, enabled=payload.enabled)
    # 审计（不含 api_key 明文）
    admin_service._audit(
        db,
        actor=admin,
        action="set_global_llm",
        target_type="system_setting",
        target_id="llm_global_config",
        detail={
            "enabled": payload.enabled,
            "chat_base_url": payload.chat_config.base_url if payload.chat_config else None,
            "chat_model": payload.chat_config.model if payload.chat_config else None,
        },
    )
    return {
        "llm_global_enabled": payload.enabled,
        "chat_config": llm_config_service.get_global_chat_settings(db),
    }


def _resolve_admin_test_values(payload, db):
    """两模式：传值 → 用传入值；不传 → 用已存的 SystemSetting chat 配置复检。"""
    base_url = payload.base_url
    api_key = payload.api_key
    model = payload.model
    if not (base_url and api_key and model):
        cfg = db.scalar(select(SystemSetting).where(SystemSetting.key == "llm_global_chat_config"))
        stored = cfg.value if cfg else {}
        base_url = base_url or stored.get("base_url", "")
        model = model or stored.get("model", "")
        enc = stored.get("api_key_encrypted")
        api_key = api_key or (decrypt_value(enc) if enc else "")
    return base_url, api_key, model


@router.post("/admin/llm-config/chat/test")
def test_global_chat(
    payload: GlobalScopeTestRequest,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    base_url, api_key, model = _resolve_admin_test_values(payload, db)
    if not (base_url and api_key and model):
        return {"ok": False, "chat": {"ok": False, "latency_ms": None, "sample": None, "error": "全局 chat 配置未设置完整"}, "embedding": None, "error": "全局 chat 配置未设置完整（缺 base_url / api_key / model）"}
    return llm_config_service.test_llm_connection(base_url=base_url, api_key=api_key, model=model, scope="chat")


@router.post("/admin/llm-config/chat/models")
def list_global_chat_models(
    payload: ListModelsRequest,
    admin: User = Depends(require_admin),
):
    return llm_config_service.list_provider_models(base_url=payload.base_url, api_key=payload.api_key, provider_template_id=payload.provider_template_id)


# ── 轻量任务模型配置（独立第三套；承接会话标题/章节摘要等轻量任务）──
# 与上方全局 chat 配置同构：未配即回退 chat，无 enabled 开关。

@router.get("/admin/lite-config")
def get_lite_llm(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return llm_config_service.get_lite_settings(db)


@router.put("/admin/lite-config")
def set_lite_llm(
    payload: LiteSettings,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if payload.lite_config:
        c = payload.lite_config
        llm_config_service.set_lite_settings(
            db, base_url=c.base_url, api_key=c.api_key, model=c.model,
        )
    # 审计（不含 api_key 明文）
    admin_service._audit(
        db,
        actor=admin,
        action="set_lite_config",
        target_type="system_setting",
        target_id="llm_lite_config",
        detail={
            "lite_base_url": payload.lite_config.base_url if payload.lite_config else None,
            "lite_model": payload.lite_config.model if payload.lite_config else None,
        },
    )
    return llm_config_service.get_lite_settings(db)


def _resolve_lite_test_values(payload, db):
    """两模式：传值 → 用传入值；不传 → 用已存的 llm_lite_config 复检。"""
    base_url = payload.base_url
    api_key = payload.api_key
    model = payload.model
    if not (base_url and api_key and model):
        cfg = db.scalar(select(SystemSetting).where(SystemSetting.key == "llm_lite_config"))
        stored = cfg.value if cfg else {}
        base_url = base_url or stored.get("base_url", "")
        model = model or stored.get("model", "")
        enc = stored.get("api_key_encrypted")
        api_key = api_key or (decrypt_value(enc) if enc else "")
    return base_url, api_key, model


@router.post("/admin/lite-config/test")
def test_lite_llm(
    payload: GlobalScopeTestRequest,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    base_url, api_key, model = _resolve_lite_test_values(payload, db)
    if not (base_url and api_key and model):
        return {"ok": False, "chat": {"ok": False, "latency_ms": None, "sample": None, "error": "轻量任务模型配置未设置完整"}, "embedding": None, "error": "轻量任务模型配置未设置完整（缺 base_url / api_key / model）"}
    return llm_config_service.test_llm_connection(base_url=base_url, api_key=api_key, model=model, scope="chat")


@router.post("/admin/lite-config/models")
def list_lite_models(
    payload: ListModelsRequest,
    admin: User = Depends(require_admin),
):
    return llm_config_service.list_provider_models(base_url=payload.base_url, api_key=payload.api_key, provider_template_id=payload.provider_template_id)


# ── Firecrawl 配置(网页摄入)──────────────────────────────────


class FirecrawlConfigRequest(BaseModel):
    """admin 设置全局 Firecrawl 配置。

    api_key 空串表示不修改(保留现有 key)。
    base_url 为 None 表示不修改(保留现有 base_url),对齐 api_key 空串=不改的语义。
    显式传值(含空串)才覆盖。
    """

    enabled: bool
    api_key: str = ""
    base_url: str | None = None


@router.get("/admin/console/firecrawl")
def get_firecrawl_config(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """读全局 Firecrawl 配置(api_key 脱敏)。"""
    from app.services.firecrawl_client import get_firecrawl_settings

    return get_firecrawl_settings(db)


@router.put("/admin/console/firecrawl")
def set_firecrawl_config(
    payload: FirecrawlConfigRequest,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """写全局 Firecrawl 配置。"""
    from app.services.firecrawl_client import set_firecrawl_settings

    set_firecrawl_settings(
        db, enabled=payload.enabled, api_key=payload.api_key,
        base_url=payload.base_url, updated_by=admin.id,
    )
    return {"ok": True}


# ── MinerU 配置（PDF→Markdown 解析）───────────────────────────


class MineruConfigRequest(BaseModel):
    """admin 设置全局 MinerU 配置。api_token 空串=不改（保留现有）。"""
    enabled: bool
    api_token: str = ""
    base_url: str | None = None
    model_version: str | None = None


@router.get("/admin/console/mineru")
def get_mineru_config(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """读全局 MinerU 配置（api_token 脱敏）。"""
    from app.services.mineru_client import get_mineru_settings

    return get_mineru_settings(db)


@router.put("/admin/console/mineru")
def set_mineru_config(
    payload: MineruConfigRequest,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """写全局 MinerU 配置。"""
    from app.services.mineru_client import set_mineru_settings

    set_mineru_settings(
        db, enabled=payload.enabled, api_token=payload.api_token,
        base_url=payload.base_url, model_version=payload.model_version,
    )
    return {"ok": True}


@router.post("/admin/console/mineru/test")
def test_mineru_config(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """测试 MinerU 配置是否有效（解析一个极小 PDF 样本）。"""
    from app.services.mineru_client import resolve_mineru_config, parse_pdf_to_markdown

    cfg = resolve_mineru_config(db)
    if cfg is None:
        return {"ok": False, "message": "MinerU 未配置（需启用并填 api_token）"}
    sample_pdf = b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[3 0 R]/Count 0>>endobj\n3 0 obj<</Type/Page/Parent 2 0 R>>endobj\nxref\n0 4\ntrailer<</Root 1 0 R>>\n%%EOF"
    try:
        parse_pdf_to_markdown(db, content=sample_pdf, filename="connectivity-test.pdf")
        return {"ok": True, "message": f"MinerU 连通正常（{cfg.base_url}）"}
    except Exception as e:
        return {"ok": False, "message": f"MinerU 测试失败：{str(e)[:200]}"}


# ── ima 检索源配置（腾讯 ima 知识库全局检索源）─────────────────


class IMAConfigRequest(BaseModel):
    """admin 设置全局 ima 检索源配置。

    client_id / api_key 空串表示不修改（保留现有凭据）。
    """
    enabled: bool
    client_id: str = ""
    api_key: str = ""


class IMATestRequest(BaseModel):
    """测试 ima 连通性（不落库，用传入凭据直接检索）。"""
    client_id: str
    api_key: str


@router.get("/admin/console/ima")
def get_ima_config(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """读全局 ima 配置（凭据脱敏）。"""
    from app.services.ima_config_service import get_ima_settings

    return get_ima_settings(db)


@router.put("/admin/console/ima")
def set_ima_config(
    payload: IMAConfigRequest,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """写全局 ima 配置。"""
    from app.services.ima_config_service import set_ima_settings

    set_ima_settings(
        db, enabled=payload.enabled,
        client_id=payload.client_id, api_key=payload.api_key,
        updated_by=admin.id,
    )
    return {"ok": True}


@router.post("/admin/console/ima/test")
def test_ima_config(
    payload: IMATestRequest,
    admin: User = Depends(require_admin),
):
    """测试 ima 检索连通性（不落库）。

    用传入凭据做一次最小检索，返回成功/失败与命中数。
    strict=True：失败必须抛错，否则 fail-open 返回空列表会被误判为成功。
    """
    from app.rag.ima_source import search_ima
    from app.services.ima_config_service import ResolvedIMAConfig

    cfg = ResolvedIMAConfig(
        client_id=payload.client_id, api_key=payload.api_key, enabled=True,
    )
    try:
        hits = search_ima("测试", cfg, top_k=1, strict=True)
        return {"ok": True, "hit_count": len(hits)}
    except Exception as e:
        return {"ok": False, "error": str(e), "hit_count": 0}
