"""LLM 配置服务：chat 解析 + 用户/全局配置管理，embedding 走固定微服务。

chat 解析（resolve_chat_config）支持多源（全局/用户自配/env），由 chat_source 控制；
内部后台任务（archiver / retriever / knowledge_service / review / summary）通过
chat_source=None 走 fallback 自动解析（admin→global chat→env；非 admin→grant→
global chat→最早 chat 配置→env）。

embedding 解析（resolve_embedding_config）不再多源：统一走一个固定的 bge-m3 微服务
（OpenAI 兼容协议），连接信息从环境变量读（embedding_base_url/embedding_model/
embedding_api_key，见 core/config.py）。用户/admin 不可配 embedding。

chat source 取值：
- "global"：全局 chat Key（admin 免授权；非 admin 须有有效 grant）
- "custom-chat:{config_id}"：用户自配的指定 chat 配置（校验归属，越权 NotFound）
- "env"：env 兜底
- None：内部 fallback 路径（见上）

用户自定义配置 CRUD（list/create/update/delete_user_llm_config）只管 chat 配置；
全局配置只保留 chat 一套（get/set_global_chat_settings），admin 控制台
GET/PUT /admin/llm-config 也只管 chat。

轻量任务模型（lite config）：独立的第三套配置，承接高频轻量任务（会话标题
summarize_conversation_title、章节摘要 generate_summary），由 admin 在控制台
配置（典型 GLM-4.7-Flash，免费）。存 SystemSetting key "llm_lite_config"
（get/set_lite_settings），resolve_lite_config 解析：已配且完整 → 用轻量配置；
未配/不完整 → 回退 resolve_chat_config(user_id)，保证轻量任务不中断。轻量配置
是全平台共享的单套（不分用户），无 enabled 开关（未配即回退）。
"""

# SystemSetting key：轻量任务模型配置（独立于 llm_global_chat_config）。
LITE_CONFIG_KEY = "llm_lite_config"

import time
import uuid
from dataclasses import dataclass

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import ForbiddenError, NotFoundError, ValidationError
from app.core.security import decrypt_value, encrypt_value
from app.models import SystemSetting, User, UserGlobalLLMGrant, UserLLMConfig


# ── 用户自定义 chat 配置（多配置 CRUD，Task 2.3）──

def list_user_llm_configs(db: Session, *, user_id) -> list[dict]:
    """列出用户所有自定义 chat 配置（key 掩码）。按创建时间升序。"""
    cfgs = db.scalars(
        select(UserLLMConfig)
        .where(UserLLMConfig.user_id == user_id)
        .order_by(UserLLMConfig.created_at)
    ).all()
    return [config_to_dict(c) for c in cfgs]


def create_user_llm_config(
    db: Session, *, user_id, name: str, provider: str, base_url: str,
    api_key: str, model: str,
) -> UserLLMConfig:
    """新增一条自定义 chat 配置。"""
    cfg = UserLLMConfig(
        user_id=user_id, name=name, provider=provider, base_url=base_url,
        api_key_encrypted=encrypt_value(api_key), model=model,
    )
    db.add(cfg)
    db.commit()
    db.refresh(cfg)
    return cfg


def update_user_llm_config(
    db: Session, *, user_id, config_id, name: str | None = None,
    provider: str | None = None, base_url: str | None = None,
    api_key: str | None = None, model: str | None = None,
) -> UserLLMConfig:
    """修改指定自定义 chat 配置。仅提供才更新。越权/不存在 NotFoundError。"""
    cfg = _get_owned_config(db, user_id=user_id, config_id=config_id)  # 越权 NotFound
    if name is not None:
        cfg.name = name
    if provider is not None:
        cfg.provider = provider
    if base_url is not None:
        cfg.base_url = base_url
    if api_key is not None:
        cfg.api_key_encrypted = encrypt_value(api_key)
    if model is not None:
        cfg.model = model
    db.commit()
    db.refresh(cfg)
    return cfg


def delete_user_llm_config(db: Session, *, user_id, config_id) -> None:
    """删除指定自定义配置。越权/不存在 NotFoundError。"""
    cfg = _get_owned_config(db, user_id=user_id, config_id=config_id)
    db.delete(cfg)
    db.commit()


def _get_owned_config(db: Session, *, user_id, config_id) -> UserLLMConfig:
    """查配置并校验归属。越权/不存在 NotFoundError（防探测，不泄露存在性）。"""
    try:
        cid = uuid.UUID(config_id) if isinstance(config_id, str) else config_id
    except (ValueError, AttributeError):
        raise NotFoundError("LLM 配置不存在")
    cfg = db.get(UserLLMConfig, cid)
    if cfg is None or cfg.user_id != user_id:
        raise NotFoundError("LLM 配置不存在")
    return cfg


def config_to_dict(cfg: UserLLMConfig) -> dict:
    """自定义 chat 配置 → dict（key 掩码）。API 层和 service list 共用。"""
    return {
        "id": str(cfg.id),
        "name": cfg.name,
        "provider": cfg.provider,
        "base_url": cfg.base_url,
        "api_key_masked": _mask_key(decrypt_value(cfg.api_key_encrypted)),
        "model": cfg.model,
    }


# ── 全局配置（管理员）：见文件底部拆分版 set/get_global_chat/embedding_settings ──


def _mask_key(key: str) -> str:
    """掩码 API key（sk-****abcd）。"""
    if len(key) <= 8:
        return "****"
    return key[:3] + "****" + key[-4:]


# ── 拉取 provider 模型列表（决策 D4：httpx 直连，不绕 LangChain）──

_LIST_MODELS_MAX = 100
_LIST_MODELS_TIMEOUT = 15.0


def list_provider_models(
    db: Session | None = None, *,  # db 保留位置以兼容 service 风格，本函数不用
    base_url: str,
    api_key: str,
    provider_template_id: str | None = None,
) -> dict:
    """调 provider 的模型列表端点，返回 {models, truncated, error}。

    endpoint 路径来自 provider 模板的 models_endpoint 字段（Task 2）：
    - OpenAI 兼容（zhipu/openai/deepseek/openrouter/moonshot/custom/未指定）→ "/models"
      拼接：base_url.rstrip("/") + "/models"（base_url 已含版本段如 /v1、/v4）
    - Ollama → "/api/tags"（base_url 无版本段，如 http://localhost:11434）

    解析：OpenAI 兼容 {data:[{id}]} → 取 id；Ollama {models:[{name}]} → 取 name。
    去重 + 字母序排序；超过 100 条截断，truncated=True。
    任何错误（连接/超时/401/格式异常）→ {models:[], error:"友好"}，不抛异常。
    """
    from app.services.llm_provider_templates import get_provider_template

    # endpoint 路径：优先用模板声明；无模板则默认 OpenAI 兼容 "/models"
    endpoint_path = "/models"
    tpl = get_provider_template(provider_template_id) if provider_template_id else None
    if tpl:
        endpoint_path = tpl.models_endpoint
    base = base_url.rstrip("/")
    url = f"{base}{endpoint_path}"

    try:
        resp = httpx.get(
            url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=_LIST_MODELS_TIMEOUT,
        )
    except httpx.TimeoutException:
        return {"models": [], "truncated": False, "error": "拉取模型超时，请检查网络或端点"}
    except httpx.HTTPError:
        return {"models": [], "truncated": False, "error": f"无法连接到 {base}，请检查 base_url"}

    if resp.status_code in (401, 403):
        return {"models": [], "truncated": False, "error": "API Key 无效或无权限（401/403）"}
    if resp.status_code != 200:
        return {"models": [], "truncated": False,
                "error": f"拉取失败：HTTP {resp.status_code}"}

    try:
        body = resp.json()
    except Exception:
        return {"models": [], "truncated": False, "error": "响应非 JSON，无法解析"}

    # OpenAI 兼容：{data:[{id}]}；Ollama：{models:[{name}]}
    raw: list[str] = []
    if isinstance(body, dict) and isinstance(body.get("data"), list):
        raw = [item.get("id") for item in body["data"]
               if isinstance(item, dict) and item.get("id")]
    elif isinstance(body, dict) and isinstance(body.get("models"), list):
        raw = [item.get("name") for item in body["models"]
               if isinstance(item, dict) and item.get("name")]
    else:
        return {"models": [], "truncated": False,
                "error": "响应格式无法解析（期望 data[].id 或 models[].name）"}

    # 去重 + 排序 + 截断
    unique = sorted(set(raw))
    truncated = len(unique) > _LIST_MODELS_MAX
    return {"models": unique[:_LIST_MODELS_MAX], "truncated": truncated, "error": None}


# ── 测试连通性（增强版：chat + embedding 双测）──

_TEST_TIMEOUT = 15


def test_llm_connection(
    db: Session | None = None, *,  # 保留位置兼容 service 风格，本函数不用
    base_url: str,
    api_key: str,
    model: str,
    embedding_model: str | None = None,  # 保留参数兼容调用点；embedding 已走固定服务，不再此处测
    scope: str = "chat",  # 仅 chat；embedding 由独立微服务负责，不再经此函数测
) -> dict:
    """测试 chat LLM 连通性。不落库、不写 LLMCallLog。

    embedding 的连通性不再由本函数测（embedding 统一走固定 bge-m3 微服务，
    无需在配置时测试）。scope/embedding_model 参数保留仅为避免动调用点签名，
    内部一律按 chat 处理。

    返回 TestConnectionResult：
      {ok, chat:{ok,latency_ms,sample,error}|None, embedding:None, error}
    错误经 friendly_llm_error 友好化。
    """
    from langchain_core.messages import HumanMessage
    from langchain_openai import ChatOpenAI

    from app.ai.llm_errors import friendly_llm_error

    chat = {"ok": False, "latency_ms": None, "sample": None, "error": None}
    try:
        llm = ChatOpenAI(
            model=model, base_url=base_url, api_key=api_key,
            request_timeout=_TEST_TIMEOUT,
        )
        t0 = time.perf_counter()
        resp = llm.invoke([HumanMessage(content="hi")])
        chat["latency_ms"] = int((time.perf_counter() - t0) * 1000)
        chat["ok"] = True
        chat["sample"] = (resp.content or "")[:50]
    except Exception as e:
        chat["error"] = friendly_llm_error(e)

    ok = chat["ok"]
    return {
        "ok": ok,
        "chat": chat,
        "embedding": None,
        "error": None if ok else chat["error"],
    }


# ════════════════════════════════════════════════════════════
# chat / embedding 独立凭据解析（Task 3 拆分；旧耦合版已删除）
# ════════════════════════════════════════════════════════════


@dataclass
class ResolvedChatConfig:
    """解析后的 chat 配置（独立于 embedding）。"""
    base_url: str
    api_key: str
    model: str
    source: str = "user"


@dataclass
class ResolvedEmbeddingConfig:
    """解析后的 embedding 配置（独立于 chat）。"""
    base_url: str
    api_key: str
    model: str
    source: str = "user"


# ── chat 解析 ──

def resolve_chat_config(db: Session, *, user_id, chat_source: str | None = None) -> ResolvedChatConfig | None:
    """解析 chat 配置。

    chat_source 取值：
    - "global"：全局 chat Key（admin 免授权；非 admin 须有效 grant）
    - "custom-chat:{id}"：用户自配的指定 chat 配置（越权 NotFound）
    - "env"：env 兜底
    - None：内部 fallback（admin→global chat→env；非 admin→grant→global chat→最早 chat 配置→env）
    """
    user = db.get(User, user_id)
    if chat_source is None:
        return _resolve_chat_fallback(db, user=user, user_id=user_id)

    if chat_source == "global":
        if user and user.role == "admin":
            return _build_global_chat_config(db, source="admin")
        grant = _get_active_grant(db, user_id)
        if not grant:
            raise ForbiddenError("未授权使用全局 chat Key，请在设置中添加自定义配置")
        return _build_global_chat_config(db, source="global")

    if chat_source.startswith("custom-chat:"):
        config_id = chat_source[len("custom-chat:"):]
        cfg = _get_chat_config_by_id(db, user_id=user_id, config_id=config_id)
        if cfg is None:
            raise NotFoundError("chat 配置不存在")
        return ResolvedChatConfig(
            base_url=cfg.base_url,
            api_key=decrypt_value(cfg.api_key_encrypted),
            model=cfg.model,
            source="user",
        )

    if chat_source == "env":
        return _build_env_chat_config()

    raise ValidationError(f"无效的 chat_source: {chat_source}")


def _resolve_chat_fallback(db: Session, *, user, user_id) -> ResolvedChatConfig | None:
    if user and user.role == "admin":
        cfg = _build_global_chat_config(db, source="admin")
        if cfg:
            return cfg
        return _build_env_chat_config()
    grant = _get_active_grant(db, user_id)
    if grant:
        cfg = _build_global_chat_config(db, source="global")
        if cfg:
            return cfg
    user_cfg = db.scalar(
        select(UserLLMConfig)
        .where(UserLLMConfig.user_id == user_id)
        .order_by(UserLLMConfig.created_at)
    )
    if user_cfg:
        return ResolvedChatConfig(
            base_url=user_cfg.base_url,
            api_key=decrypt_value(user_cfg.api_key_encrypted),
            model=user_cfg.model,
            source="user",
        )
    return _build_env_chat_config()


def _build_global_chat_config(db: Session, *, source: str) -> ResolvedChatConfig | None:
    enabled_setting = db.scalar(select(SystemSetting).where(SystemSetting.key == "llm_global_enabled"))
    if enabled_setting and enabled_setting.value and enabled_setting.value.get("enabled") is False:
        return None
    cfg = db.scalar(select(SystemSetting).where(SystemSetting.key == "llm_global_chat_config"))
    if cfg and cfg.value and cfg.value.get("api_key_encrypted") and cfg.value.get("model"):
        v = cfg.value
        return ResolvedChatConfig(
            base_url=v.get("base_url", ""),
            api_key=decrypt_value(v["api_key_encrypted"]),
            model=v.get("model", ""),
            source=source,
        )
    return None


def _build_env_chat_config() -> ResolvedChatConfig | None:
    from app.core.config import get_settings
    s = get_settings()
    if s.glm_api_key:
        return ResolvedChatConfig(
            base_url=s.glm_base_url,
            api_key=s.glm_api_key,
            model=s.glm_model,
            source="env",
        )
    return None


def _get_chat_config_by_id(db: Session, *, user_id, config_id) -> UserLLMConfig | None:
    try:
        cid = uuid.UUID(config_id) if isinstance(config_id, str) else config_id
    except (ValueError, AttributeError):
        return None
    cfg = db.get(UserLLMConfig, cid)
    if cfg is None or cfg.user_id != user_id:
        return None
    return cfg


# ── embedding 解析（统一走固定 bge-m3 微服务，无多源）──

def resolve_embedding_config(
    db: Session | None = None, *, user_id=None,
    embedding_source: str | None = None,  # 保留参数兼容调用点；已无实际作用
) -> ResolvedEmbeddingConfig:
    """返回 embedding 配置。统一走固定的 bge-m3 微服务（OpenAI 兼容协议），
    连接信息从环境变量读（embedding_base_url/embedding_model/embedding_api_key）。

    不再支持多源（全局/用户自配/env fallback），用户/admin 不可配 embedding。
    db / user_id / embedding_source 参数保留仅为避免动 3 个内部调用方签名，
    内部一律返回固定配置（永不为 None）。
    """
    from app.core.config import get_settings
    s = get_settings()
    return ResolvedEmbeddingConfig(
        base_url=s.embedding_base_url,
        api_key=s.embedding_api_key,
        model=s.embedding_model,
        source="service",
    )


def _get_active_grant(db: Session, user_id):
    """共享辅助：查有效 grant（chat 的全局 Key 授权门禁用）。"""
    return db.scalar(select(UserGlobalLLMGrant).where(
        (UserGlobalLLMGrant.user_id == user_id) &
        (UserGlobalLLMGrant.revoked_at.is_(None))
    ))


# ── 全局 chat 配置（embedding 已无全局配置，走固定微服务）──

def get_global_chat_settings(db: Session) -> dict:
    cfg = db.scalar(select(SystemSetting).where(SystemSetting.key == "llm_global_chat_config"))
    return {
        "base_url": cfg.value.get("base_url", "") if cfg else "",
        "api_key_masked": _mask_key(decrypt_value(cfg.value["api_key_encrypted"])) if cfg and cfg.value.get("api_key_encrypted") else "",
        "model": cfg.value.get("model", "") if cfg else "",
    }


def set_global_chat_settings(
    db: Session, *, enabled: bool, base_url: str | None = None,
    api_key: str | None = None, model: str | None = None,
) -> dict:
    """enabled 开关（llm_global_enabled）现在仅控制 chat（embedding 已走固定服务）。"""
    setting = db.scalar(select(SystemSetting).where(SystemSetting.key == "llm_global_enabled"))
    if setting:
        setting.value = {"enabled": enabled}
    else:
        db.add(SystemSetting(key="llm_global_enabled", value={"enabled": enabled}))

    if base_url or api_key or model:
        cfg = db.scalar(select(SystemSetting).where(SystemSetting.key == "llm_global_chat_config"))
        current = cfg.value if cfg else {}
        new_value = {
            "base_url": base_url or current.get("base_url", ""),
            "model": model or current.get("model", ""),
        }
        if api_key:
            new_value["api_key_encrypted"] = encrypt_value(api_key)
        elif current.get("api_key_encrypted"):
            new_value["api_key_encrypted"] = current["api_key_encrypted"]
        if cfg:
            cfg.value = new_value
        else:
            db.add(SystemSetting(key="llm_global_chat_config", value=new_value))
    db.commit()
    return get_global_chat_settings(db)


# ── 轻量任务模型配置（独立第三套；承接会话标题/章节摘要等轻量任务）──

def get_lite_settings(db: Session) -> dict:
    """读取轻量任务模型配置（key 掩码）。与 get_global_chat_settings 同构，
    额外返回 configured 标志（前端据此提示是否已配/回退到 chat）。"""
    cfg = db.scalar(select(SystemSetting).where(SystemSetting.key == LITE_CONFIG_KEY))
    value = cfg.value if cfg else {}
    configured = bool(value.get("api_key_encrypted") and value.get("model"))
    return {
        "base_url": value.get("base_url", "") if cfg else "",
        "api_key_masked": _mask_key(decrypt_value(value["api_key_encrypted"])) if configured else "",
        "model": value.get("model", "") if cfg else "",
        "configured": configured,
    }


def set_lite_settings(
    db: Session, *, base_url: str | None = None,
    api_key: str | None = None, model: str | None = None,
) -> dict:
    """保存轻量任务模型配置。无 enabled 开关（未配即回退 chat）。

    api_key 留空 = 不修改（保留现有密钥），与 set_global_chat_settings 语义一致。
    """
    if base_url or api_key or model:
        cfg = db.scalar(select(SystemSetting).where(SystemSetting.key == LITE_CONFIG_KEY))
        current = cfg.value if cfg else {}
        new_value = {
            "base_url": base_url or current.get("base_url", ""),
            "model": model or current.get("model", ""),
        }
        if api_key:
            new_value["api_key_encrypted"] = encrypt_value(api_key)
        elif current.get("api_key_encrypted"):
            new_value["api_key_encrypted"] = current["api_key_encrypted"]
        if cfg:
            cfg.value = new_value
        else:
            db.add(SystemSetting(key=LITE_CONFIG_KEY, value=new_value))
        db.commit()
    return get_lite_settings(db)


def resolve_lite_config(db: Session, *, user_id) -> ResolvedChatConfig | None:
    """解析轻量任务模型配置。

    优先用 admin 配的 llm_lite_config（典型 GLM-4.7-Flash）；未配/不完整时回退
    resolve_chat_config(user_id)，保证轻量任务（标题/摘要）不中断——轻量任务本
    就允许失败降级，回退到 chat 模型只是「省钱目标暂未达成」，而非功能损坏。

    轻量配置是全平台共享的单套（不分用户），不查 grant/user_llm_config。
    返回 source="lite" 便于日志区分实际命中的是轻量配置还是 chat 回退。
    """
    cfg = db.scalar(select(SystemSetting).where(SystemSetting.key == LITE_CONFIG_KEY))
    if cfg and cfg.value and cfg.value.get("api_key_encrypted") and cfg.value.get("model"):
        v = cfg.value
        return ResolvedChatConfig(
            base_url=v.get("base_url", ""),
            api_key=decrypt_value(v["api_key_encrypted"]),
            model=v.get("model", ""),
            source="lite",
        )
    return resolve_chat_config(db, user_id=user_id)
