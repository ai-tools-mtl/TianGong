"""LLM 配置服务：chat / embedding 独立解析 + 用户/全局配置管理。

chat 解析（resolve_chat_config）与 embedding 解析（resolve_embedding_config）
完全独立：各自的 source 取值、fallback 不互通（D4）。内部后台任务（archiver /
retriever / knowledge_service / review / summary）通过 chat_source=None 自动
解析路径调用（admin→global chat→env；非 admin→grant→global chat→最早 chat 配置→env）。

chat source 取值：
- "global"：全局 chat Key（admin 免授权；非 admin 须有有效 grant）
- "custom-chat:{config_id}"：用户自配的指定 chat 配置（校验归属，越权 NotFound）
- "env"：env 兜底
- None：内部 fallback 路径（见上）

用户自定义配置 CRUD（list/create/update/delete_user_llm_config）只管 chat 配置；
全局配置仍保留耦合版 get/set_global_llm_settings（admin 控制台使用，字段含
embedding_model/allowed_models）。
"""

import time
import uuid
from dataclasses import dataclass

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import ForbiddenError, NotFoundError, ValidationError
from app.core.security import decrypt_value, encrypt_value
from app.models import SystemSetting, User, UserEmbeddingConfig, UserGlobalLLMGrant, UserLLMConfig


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


# ── 全局配置（管理员）──

def get_global_llm_settings(db: Session) -> dict:
    """获取全局 LLM 设置（掩码 key）。

    enabled 默认值与 `_build_global_chat_config` 的 enabled 检查对齐：记录不存在时视为开启（True），
    避免 admin UI 显示「关闭」但 resolve 实际当「开启」的不一致（I-1）。
    """
    enabled = db.scalar(select(SystemSetting).where(SystemSetting.key == "llm_global_enabled"))
    cfg = db.scalar(select(SystemSetting).where(SystemSetting.key == "llm_global_config"))
    return {
        "llm_global_enabled": enabled.value.get("enabled", True) if enabled else True,
        "global_config": {
            "base_url": cfg.value.get("base_url", "") if cfg else "",
            "api_key_masked": _mask_key(decrypt_value(cfg.value["api_key_encrypted"])) if cfg and cfg.value.get("api_key_encrypted") else "",
            "model": cfg.value.get("model", "") if cfg else "",
            "embedding_model": cfg.value.get("embedding_model") if cfg else None,
            "allowed_models": cfg.value.get("allowed_models") if cfg else [],
        } if cfg else None,
    }


def set_global_llm_settings(
    db: Session, *, enabled: bool, base_url: str | None = None,
    api_key: str | None = None, model: str | None = None,
    embedding_model: str | None = None,
    allowed_models: list[str] | None = None,
) -> dict:
    """管理员设置全局 LLM。

    - enabled: 开关（总是写入）。
    - base_url/api_key/model/embedding_model: 提供才更新，不提供保留现有。
    - allowed_models: 提供则覆盖（含空 list 清空），不提供保留现有。
    """
    # 开关
    setting = db.scalar(select(SystemSetting).where(SystemSetting.key == "llm_global_enabled"))
    if setting:
        setting.value = {"enabled": enabled}
    else:
        db.add(SystemSetting(key="llm_global_enabled", value={"enabled": enabled}))

    # 配置：有任一字段提供则更新（含 allowed_models 显式空 list / embedding_model 空串清空场景）。
    # 注意 embedding_model 用 `is not None`，否则 "" 无法清空（I2）。
    if (base_url or api_key or model
            or embedding_model is not None
            or allowed_models is not None):
        cfg = db.scalar(select(SystemSetting).where(SystemSetting.key == "llm_global_config"))
        current = cfg.value if cfg else {}
        new_value = {
            "base_url": base_url or current.get("base_url", ""),
            "model": model or current.get("model", ""),
        }
        # embedding_model: 提供则更新（含空串清空，I2 修复），否则保留现有。
        # 注意用 `is not None` 而非 truthiness，否则 "" 无法清空。
        if embedding_model is not None:
            new_value["embedding_model"] = embedding_model
        elif current.get("embedding_model") is not None:
            new_value["embedding_model"] = current["embedding_model"]
        # allowed_models: 提供则覆盖（含空 list），否则保留现有
        if allowed_models is not None:
            new_value["allowed_models"] = list(allowed_models)
        elif current.get("allowed_models"):
            new_value["allowed_models"] = current["allowed_models"]
        if api_key:
            new_value["api_key_encrypted"] = encrypt_value(api_key)
        elif current.get("api_key_encrypted"):
            new_value["api_key_encrypted"] = current["api_key_encrypted"]

        if cfg:
            cfg.value = new_value
        else:
            db.add(SystemSetting(key="llm_global_config", value=new_value))

    db.commit()
    return get_global_llm_settings(db)


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
    embedding_model: str | None = None,
    scope: str = "all",  # "all"（chat+embedding，需 embedding_model）/ "chat"（只 chat）/ "embedding"（只 embedding）
) -> dict:
    """测试 LLM 连通性。scope 控制测什么。不落库、不写 LLMCallLog。

    - scope="all"：chat 必测；embedding_model 提供则一并测（兼容旧默认行为）。
    - scope="chat"：只测 chat（忽略 embedding_model）。
    - scope="embedding"：只测 embedding（model 参数当 embedding 模型名用）。

    返回 TestConnectionResult：
      {ok, chat:{ok,latency_ms,sample,error}|None, embedding:{ok,latency_ms,dim,error}|None, error}
    chat 与 embedding 独立 try/except，互不影响。
    所有错误经 friendly_llm_error 友好化。
    """
    from langchain_core.messages import HumanMessage
    from langchain_openai import ChatOpenAI, OpenAIEmbeddings

    from app.ai.llm_errors import friendly_llm_error

    # ---- chat（scope=all 或 chat 时测）----
    chat = None
    if scope in ("all", "chat"):
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

    # ---- embedding（scope=embedding，或 scope=all 且 embedding_model 非空时测）----
    # embedding scope 下 model 即 emb 模型名（无需另传 embedding_model）
    embedding = None
    emb_model = embedding_model if scope != "embedding" else model
    if scope == "embedding" or (scope == "all" and emb_model):
        embedding = {"ok": False, "latency_ms": None, "dim": None, "error": None}
        try:
            emb = OpenAIEmbeddings(
                model=emb_model, base_url=base_url, api_key=api_key,
                request_timeout=_TEST_TIMEOUT,
            )
            t0 = time.perf_counter()
            vec = emb.embed_query("hi")
            embedding["latency_ms"] = int((time.perf_counter() - t0) * 1000)
            embedding["ok"] = True
            embedding["dim"] = len(vec) if vec else None
        except Exception as e:
            embedding["error"] = friendly_llm_error(e)

    tested = [x for x in (chat, embedding) if x is not None]
    ok = all(x["ok"] for x in tested) if tested else False
    first_err = next((x["error"] for x in tested if x["error"]), None)
    return {
        "ok": ok,
        "chat": chat,
        "embedding": embedding,
        "error": None if ok else first_err,
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


# ── embedding 解析（与 chat 完全独立，fallback 不互通，D4）──

def resolve_embedding_config(db: Session, *, user_id, embedding_source: str | None = None) -> ResolvedEmbeddingConfig | None:
    """解析 embedding 配置。与 chat 完全独立（fallback 不互通，D4）。

    embedding_source 取值：
    - "global"：全局 embedding Key（admin 免授权；非 admin 须有效 grant）
    - "custom-emb:{id}"：用户自配的指定 embedding 配置（越权 NotFound）
    - "env"：env 兜底
    - None：内部 fallback（admin→global emb→env；非 admin→grant→global emb→最早 emb 配置→env）
    """
    user = db.get(User, user_id)
    if embedding_source is None:
        return _resolve_embedding_fallback(db, user=user, user_id=user_id)

    if embedding_source == "global":
        if user and user.role == "admin":
            return _build_global_embedding_config(db, source="admin")
        grant = _get_active_grant(db, user_id)
        if not grant:
            raise ForbiddenError("未授权使用全局 embedding Key，请在设置中添加自定义配置")
        return _build_global_embedding_config(db, source="global")

    if embedding_source.startswith("custom-emb:"):
        config_id = embedding_source[len("custom-emb:"):]
        cfg = _get_embedding_config_by_id(db, user_id=user_id, config_id=config_id)
        if cfg is None:
            raise NotFoundError("embedding 配置不存在")
        return ResolvedEmbeddingConfig(
            base_url=cfg.base_url,
            api_key=decrypt_value(cfg.api_key_encrypted),
            model=cfg.model,
            source="user",
        )

    if embedding_source == "env":
        return _build_env_embedding_config()

    raise ValidationError(f"无效的 embedding_source: {embedding_source}")


def _resolve_embedding_fallback(db: Session, *, user, user_id) -> ResolvedEmbeddingConfig | None:
    if user and user.role == "admin":
        cfg = _build_global_embedding_config(db, source="admin")
        if cfg:
            return cfg
        return _build_env_embedding_config()
    grant = _get_active_grant(db, user_id)
    if grant:
        cfg = _build_global_embedding_config(db, source="global")
        if cfg:
            return cfg
    emb_cfg = db.scalar(
        select(UserEmbeddingConfig)
        .where(UserEmbeddingConfig.user_id == user_id)
        .order_by(UserEmbeddingConfig.created_at)
    )
    if emb_cfg:
        return ResolvedEmbeddingConfig(
            base_url=emb_cfg.base_url,
            api_key=decrypt_value(emb_cfg.api_key_encrypted),
            model=emb_cfg.model,
            source="user",
        )
    return _build_env_embedding_config()


def _build_global_embedding_config(db: Session, *, source: str) -> ResolvedEmbeddingConfig | None:
    enabled_setting = db.scalar(select(SystemSetting).where(SystemSetting.key == "llm_global_enabled"))
    if enabled_setting and enabled_setting.value and enabled_setting.value.get("enabled") is False:
        return None
    cfg = db.scalar(select(SystemSetting).where(SystemSetting.key == "llm_global_embedding_config"))
    if cfg and cfg.value and cfg.value.get("api_key_encrypted") and cfg.value.get("model"):
        v = cfg.value
        return ResolvedEmbeddingConfig(
            base_url=v.get("base_url", ""),
            api_key=decrypt_value(v["api_key_encrypted"]),
            model=v.get("model", ""),
            source=source,
        )
    return None


def _build_env_embedding_config() -> ResolvedEmbeddingConfig | None:
    from app.core.config import get_settings
    s = get_settings()
    if s.glm_api_key and s.glm_embedding_model:
        return ResolvedEmbeddingConfig(
            base_url=s.glm_base_url,
            api_key=s.glm_api_key,
            model=s.glm_embedding_model,
            source="env",
        )
    return None


def _get_embedding_config_by_id(db: Session, *, user_id, config_id) -> UserEmbeddingConfig | None:
    try:
        cid = uuid.UUID(config_id) if isinstance(config_id, str) else config_id
    except (ValueError, AttributeError):
        return None
    cfg = db.get(UserEmbeddingConfig, cid)
    if cfg is None or cfg.user_id != user_id:
        return None
    return cfg


def _get_active_grant(db: Session, user_id):
    """共享辅助：查有效 grant（chat 与 embedding 共用一个 grant，D5）。"""
    return db.scalar(select(UserGlobalLLMGrant).where(
        (UserGlobalLLMGrant.user_id == user_id) &
        (UserGlobalLLMGrant.revoked_at.is_(None))
    ))


# ── embedding 配置 CRUD（镜像 chat）──

def list_user_embedding_configs(db: Session, *, user_id) -> list[dict]:
    cfgs = db.scalars(
        select(UserEmbeddingConfig)
        .where(UserEmbeddingConfig.user_id == user_id)
        .order_by(UserEmbeddingConfig.created_at)
    ).all()
    return [embedding_config_to_dict(c) for c in cfgs]


def create_user_embedding_config(
    db: Session, *, user_id, name: str, base_url: str,
    api_key: str, model: str,
) -> UserEmbeddingConfig:
    cfg = UserEmbeddingConfig(
        user_id=user_id, name=name, base_url=base_url,
        api_key_encrypted=encrypt_value(api_key), model=model,
    )
    db.add(cfg); db.commit(); db.refresh(cfg)
    return cfg


def update_user_embedding_config(
    db: Session, *, user_id, config_id, name: str | None = None,
    base_url: str | None = None, api_key: str | None = None, model: str | None = None,
) -> UserEmbeddingConfig:
    cfg = _get_owned_embedding_config(db, user_id=user_id, config_id=config_id)
    if name is not None:
        cfg.name = name
    if base_url is not None:
        cfg.base_url = base_url
    if api_key is not None:
        cfg.api_key_encrypted = encrypt_value(api_key)
    if model is not None:
        cfg.model = model
    db.commit(); db.refresh(cfg)
    return cfg


def delete_user_embedding_config(db: Session, *, user_id, config_id) -> None:
    cfg = _get_owned_embedding_config(db, user_id=user_id, config_id=config_id)
    db.delete(cfg); db.commit()


def _get_owned_embedding_config(db: Session, *, user_id, config_id) -> UserEmbeddingConfig:
    try:
        cid = uuid.UUID(config_id) if isinstance(config_id, str) else config_id
    except (ValueError, AttributeError):
        raise NotFoundError("embedding 配置不存在")
    cfg = db.get(UserEmbeddingConfig, cid)
    if cfg is None or cfg.user_id != user_id:
        raise NotFoundError("embedding 配置不存在")
    return cfg


def embedding_config_to_dict(cfg: UserEmbeddingConfig) -> dict:
    return {
        "id": str(cfg.id),
        "name": cfg.name,
        "base_url": cfg.base_url,
        "api_key_masked": _mask_key(decrypt_value(cfg.api_key_encrypted)),
        "model": cfg.model,
    }


# ── 全局 chat / embedding 配置（拆两套 SystemSetting key）──

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
    """注意：enabled 开关是 chat+embedding 共用的（llm_global_enabled）。本函数也写它。"""
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


def get_global_embedding_settings(db: Session) -> dict:
    cfg = db.scalar(select(SystemSetting).where(SystemSetting.key == "llm_global_embedding_config"))
    return {
        "base_url": cfg.value.get("base_url", "") if cfg else "",
        "api_key_masked": _mask_key(decrypt_value(cfg.value["api_key_encrypted"])) if cfg and cfg.value.get("api_key_encrypted") else "",
        "model": cfg.value.get("model", "") if cfg else "",
    }


def set_global_embedding_settings(
    db: Session, *, enabled: bool, base_url: str | None = None,
    api_key: str | None = None, model: str | None = None,
) -> dict:
    setting = db.scalar(select(SystemSetting).where(SystemSetting.key == "llm_global_enabled"))
    if setting:
        setting.value = {"enabled": enabled}
    else:
        db.add(SystemSetting(key="llm_global_enabled", value={"enabled": enabled}))

    if base_url or api_key or model:
        cfg = db.scalar(select(SystemSetting).where(SystemSetting.key == "llm_global_embedding_config"))
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
            db.add(SystemSetting(key="llm_global_embedding_config", value=new_value))
    db.commit()
    return get_global_embedding_settings(db)
