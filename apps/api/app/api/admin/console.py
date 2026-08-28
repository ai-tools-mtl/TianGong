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
from app.services import (  # noqa: F401  (feedback_service: 批次 H 反馈聚合)
    admin_service,
    feedback_service,
    llm_config_service,
    stats_service,
)

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


# ── AI 输出反馈聚合（批次 H：好坏比/标签分布/坏评按章节 top）──

@router.get("/admin/stats/feedback")
def get_feedback_stats_endpoint(
    days: int = 30,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """AI 输出反馈聚合（内测迭代信号；不做逐条审核台）。"""
    if days < 1 or days > 365:
        days = 30
    return feedback_service.get_feedback_summary(db, days=days)


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


# ── LLM 余额探测与低额告警（优化计划批次 2b）──


class BalanceThresholdBody(BaseModel):
    """低额阈值（CNY）。"""
    threshold: float = Field(..., ge=0)


@router.get("/admin/llm-balance")
def get_llm_balance(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """余额告警状态：当前阈值 + 最近一次探测结果（无则 last=None）。"""
    from app.services import llm_balance_service
    return {
        "threshold": llm_balance_service.get_threshold(db),
        "last": llm_balance_service.get_last_status(db),
    }


@router.post("/admin/llm-balance/probe")
def probe_llm_balance(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """立即探测全局 chat 账户余额（仅 DeepSeek 支持；结果落库供横幅轮询）。"""
    from app.services import llm_balance_service
    return llm_balance_service.probe_balance(db)


@router.put("/admin/llm-balance/threshold")
def set_llm_balance_threshold(
    payload: BalanceThresholdBody,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """设置低额告警阈值（CNY）。"""
    from app.services import llm_balance_service
    llm_balance_service.set_threshold(db, threshold=payload.threshold)
    return {"threshold": payload.threshold}


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
        # 用领域通用词验证检索链路：鉴权通过 + 两步检索 + 能返回真实片段。
        # 不用"测试"这类无意义词（命中率低，会误判为未连通）。
        hits = search_ima("专利", cfg, top_k=3, strict=True)
        return {"ok": True, "hit_count": len(hits)}
    except Exception as e:
        return {"ok": False, "error": str(e), "hit_count": 0}


# ── 附图风格预设 ───────────────────────────────────────────────────────────────


class FigurePresetUpdate(BaseModel):
    """admin 微调单个预设的可调字段（白名单内）。"""
    font_family: str | None = None
    font_size: int | None = None
    line_width: float | None = None


@router.get("/admin/console/figure-presets")
def get_figure_presets(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """读取 3 个预设的生效参数（内置默认 + admin 微调合并）。"""
    from app.services.figure_preset_service import get_figure_presets as _get
    return {"presets": _get(db)}


@router.put("/admin/console/figure-presets/{preset_id}")
def set_figure_preset(
    preset_id: str,
    payload: FigurePresetUpdate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """微调单个预设（仅 font_family/font_size/line_width 生效，其余忽略）。写审计。"""
    from app.services import admin_service
    from app.services.figure_preset_service import set_figure_preset as _set

    overrides = {k: v for k, v in payload.model_dump().items() if v is not None}
    updated = _set(db, preset_id=preset_id, overrides=overrides, updated_by=admin.id)
    admin_service._audit(
        db, actor=admin, action="set_figure_preset",
        target_type="system_setting", target_id="figure_style_presets",
        detail={"preset_id": preset_id, **overrides},
    )
    return updated


# ── HITL 工具确认配置 ──────────────────────────────────────────────────────────


class HitlConfigUpdate(BaseModel):
    """admin 配置 agent 工具确认拦截清单。tools 为工具名列表（MCP 工具按名配置）。"""
    enabled: bool
    tools: list[str] = Field(default_factory=list)


@router.get("/admin/console/hitl")
def get_hitl_config(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """读取 HITL 拦截配置（无配置时返回默认：generate_figure）。"""
    from app.services.hitl_config_service import get_hitl_config as _get
    return _get(db)


@router.put("/admin/console/hitl")
def set_hitl_config(
    payload: HitlConfigUpdate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """保存 HITL 拦截配置（全量覆盖）。写审计。"""
    from app.services.hitl_config_service import set_hitl_config as _set

    updated = _set(db, enabled=payload.enabled, tools=payload.tools, updated_by=admin.id)
    admin_service._audit(
        db, actor=admin, action="set_hitl_config",
        target_type="system_setting", target_id="agent_hitl_config",
        detail={"enabled": payload.enabled, "tools": payload.tools},
    )
    return updated


# ── Vision 模型名单配置 ───────────────────────────────────────────────────────


class VisionMarkersUpdate(BaseModel):
    """admin 配置 vision 探测名单。extra_markers 与内置名单合并；enabled=False 禁用。"""
    enabled: bool = True
    extra_markers: list[str] = Field(default_factory=list)


@router.get("/admin/console/vision-markers")
def get_vision_markers(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """读取 vision 名单配置（无配置时返回空 extra + enabled=True 即纯内置）。"""
    from app.ai.vision import VISION_MARKERS_KEY
    from app.models import SystemSetting

    setting = db.scalar(select(SystemSetting).where(SystemSetting.key == VISION_MARKERS_KEY))
    stored = setting.value if setting and isinstance(setting.value, dict) else {}
    return {
        "enabled": bool(stored.get("enabled", True)),
        "extra_markers": stored.get("extra_markers") or [],
    }


@router.put("/admin/console/vision-markers")
def set_vision_markers(
    payload: VisionMarkersUpdate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """保存 vision 名单配置（全量覆盖）。写审计。"""
    from app.ai.vision import VISION_MARKERS_KEY
    from app.models import SystemSetting

    value = {
        "enabled": payload.enabled,
        "extra_markers": [m.strip().lower() for m in payload.extra_markers if m.strip()],
    }
    setting = db.scalar(select(SystemSetting).where(SystemSetting.key == VISION_MARKERS_KEY))
    if setting:
        setting.value = value
        setting.updated_by = admin.id
    else:
        db.add(SystemSetting(key=VISION_MARKERS_KEY, value=value, updated_by=admin.id))
    db.commit()
    admin_service._audit(
        db, actor=admin, action="set_vision_markers",
        target_type="system_setting", target_id=VISION_MARKERS_KEY,
        detail=value,
    )
    return value
