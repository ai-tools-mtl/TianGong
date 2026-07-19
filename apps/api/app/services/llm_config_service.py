"""LLM 配置服务：按 source 解析 LLM 配置 + 用户/全局配置管理（P2 白名单授权模型）。

source 取值：
- "global"：全局 Key（admin 免授权；非 admin 须有有效 grant）
- "byok:{config_id}"：用户自配的指定配置（校验归属，越权 NotFound）
- "env"：env 兜底
- None（内部调用方的自动解析路径，永久保留）：后台任务（archiver / retriever /
  knowledge_service / review / summary）无前端 source 上下文，依赖此分支
  “自动挑一个合理配置”。admin → global；非 admin → 若被授权则 global，
  否则单条 BYOK，否则 env，否则 None。
  前端 AI 调用（chat/generate/rewrite/caption）通过 source 显式指定，不走此分支。
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import ForbiddenError, NotFoundError, ValidationError
from app.core.security import decrypt_value, encrypt_value
from app.models import SystemSetting, User, UserGlobalLLMGrant, UserLLMConfig


@dataclass
class ResolvedLLMConfig:
    """解析后的生效配置。"""
    base_url: str
    api_key: str
    model: str
    embedding_model: str | None = None  # 新增（断链 A2 修复）
    source: str = "user"  # "user" / "global" / "env" / "admin"


def resolve_llm_config(db: Session, *, user_id, source: str | None = None) -> ResolvedLLMConfig | None:
    """按 source 解析 LLM 配置（P2 白名单授权模型）。

    source 取值：
    - "global"：全局 Key（admin 免授权；非 admin 须有有效 grant）
    - "byok:{config_id}"：用户自配的指定配置（校验归属，越权 NotFound）
    - "env"：env 兜底
    - None（内部调用方的自动解析路径，永久保留）：后台任务
      （archiver/retriever/knowledge_service/review/summary）无前端 source 上下文，
      依赖此分支“自动挑一个合理配置”。前端 AI 调用通过 source 显式指定，不走此分支。
    """
    user = db.get(User, user_id)

    # ---- source=None：内部调用方（archiver/retriever/knowledge/review/summary）的
    #      自动解析路径，永久保留（非临时）。前端 AI 调用始终显式传 source。
    if source is None:
        return _resolve_fallback(db, user=user, user_id=user_id)

    # ---- source 显式解析 ----
    if source == "global":
        # admin 免授权
        if user and user.role == "admin":
            return _build_global_config(db, source="admin")
        # 非 admin 须有有效 grant（revoked_at is null）
        grant = db.scalar(select(UserGlobalLLMGrant).where(
            (UserGlobalLLMGrant.user_id == user_id) &
            (UserGlobalLLMGrant.revoked_at.is_(None))
        ))
        if not grant:
            raise ForbiddenError("未授权使用全局 Key，请在设置中自配 BYOK")
        return _build_global_config(db, source="global")

    if source.startswith("byok:"):
        config_id = source[5:]
        cfg = _get_user_config_by_id(db, user_id=user_id, config_id=config_id)  # 越权 NotFound
        if cfg is None:
            raise NotFoundError("LLM 配置不存在")
        return ResolvedLLMConfig(
            base_url=cfg.base_url,
            api_key=decrypt_value(cfg.api_key_encrypted),
            model=cfg.model,
            embedding_model=cfg.embedding_model,
            source="user",
        )

    if source == "env":
        return _build_env_config()  # 返回 env 兜底或 None

    raise ValidationError(f"无效的 source: {source}")


def _resolve_fallback(db: Session, *, user, user_id) -> ResolvedLLMConfig | None:
    """内部调用方的自动解析路径（永久保留，非临时 fallback）。

    供无前端 source 上下文的后台任务使用（archiver / retriever /
    knowledge_service / review / summary，调用方共 5 处）。前端 AI 调用
    （chat/generate/rewrite/caption）通过 source 显式指定，不走此分支。

    admin → global；非 admin → 有效 grant 则 global，否则单条 BYOK，否则 env，否则 None。
    """
    if user and user.role == "admin":
        cfg = _build_global_config(db, source="admin")
        if cfg:
            return cfg
        return _build_env_config()

    # 非 admin
    grant = db.scalar(select(UserGlobalLLMGrant).where(
        (UserGlobalLLMGrant.user_id == user_id) &
        (UserGlobalLLMGrant.revoked_at.is_(None))
    ))
    if grant:
        cfg = _build_global_config(db, source="global")
        if cfg:
            return cfg

    # 单条 BYOK：内部调用方未指定 source 时的自动选择，取最早创建的一条。
    # 显式 order_by(created_at) 保证确定性选择（I-2：避免无序查询选到任意一条）。
    user_cfg = db.scalar(
        select(UserLLMConfig)
        .where(UserLLMConfig.user_id == user_id)
        .order_by(UserLLMConfig.created_at)
    )
    if user_cfg:
        return ResolvedLLMConfig(
            base_url=user_cfg.base_url,
            api_key=decrypt_value(user_cfg.api_key_encrypted),
            model=user_cfg.model,
            embedding_model=user_cfg.embedding_model,
            source="user",
        )

    return _build_env_config()


def _build_global_config(db: Session, *, source: str) -> ResolvedLLMConfig | None:
    """从 SystemSetting 构造全局配置。

    I1 修复：admin 显式关闭（llm_global_enabled 存在且 enabled=False）则不可用，
    即使配了 global_config 也返回 None。enabled 记录不存在时视为开启（兼容旧部署）。
    全局未配返回 None。
    """
    # enabled 开关（I1：admin 关闭全局则不可用；记录不存在视为开启，兼容旧部署）
    enabled_setting = db.scalar(select(SystemSetting).where(SystemSetting.key == "llm_global_enabled"))
    if enabled_setting and enabled_setting.value and enabled_setting.value.get("enabled") is False:
        return None  # admin 显式关闭

    global_cfg = db.scalar(select(SystemSetting).where(SystemSetting.key == "llm_global_config"))
    if global_cfg and global_cfg.value and global_cfg.value.get("api_key_encrypted"):
        v = global_cfg.value
        return ResolvedLLMConfig(
            base_url=v.get("base_url", ""),
            api_key=decrypt_value(v["api_key_encrypted"]),
            model=v.get("model", ""),
            embedding_model=v.get("embedding_model"),
            source=source,
        )
    return None


def _build_env_config() -> ResolvedLLMConfig | None:
    """env 兜底。glm_api_key 空则 None。"""
    from app.core.config import get_settings
    s = get_settings()
    if s.glm_api_key:
        return ResolvedLLMConfig(
            base_url=s.glm_base_url,
            api_key=s.glm_api_key,
            model=s.glm_model,
            embedding_model=s.glm_embedding_model or None,
            source="env",
        )
    return None


def _get_user_config_by_id(db: Session, *, user_id, config_id) -> UserLLMConfig | None:
    """按 id 查 BYOK 配置，校验归属。越权返回 None（调用方 NotFound，防探测）。"""
    try:
        cid = uuid.UUID(config_id) if isinstance(config_id, str) else config_id
    except (ValueError, AttributeError):
        return None
    cfg = db.get(UserLLMConfig, cid)
    if cfg is None or cfg.user_id != user_id:
        return None
    return cfg


# ── 用户 BYOK（多配置 CRUD，Task 2.3）──

def list_user_llm_configs(db: Session, *, user_id) -> list[dict]:
    """列出用户所有 BYOK 配置（key 掩码）。按创建时间升序。"""
    cfgs = db.scalars(
        select(UserLLMConfig)
        .where(UserLLMConfig.user_id == user_id)
        .order_by(UserLLMConfig.created_at)
    ).all()
    return [config_to_dict(c) for c in cfgs]


def create_user_llm_config(
    db: Session, *, user_id, name: str, provider: str, base_url: str,
    api_key: str, model: str, embedding_model: str | None = None,
) -> UserLLMConfig:
    """新增一条 BYOK 配置。"""
    cfg = UserLLMConfig(
        user_id=user_id, name=name, provider=provider, base_url=base_url,
        api_key_encrypted=encrypt_value(api_key), model=model,
        embedding_model=embedding_model,
    )
    db.add(cfg)
    db.commit()
    db.refresh(cfg)
    return cfg


def update_user_llm_config(
    db: Session, *, user_id, config_id, name: str | None = None,
    provider: str | None = None, base_url: str | None = None,
    api_key: str | None = None, model: str | None = None,
    embedding_model: str | None = None,
) -> UserLLMConfig:
    """修改指定 BYOK 配置。仅提供才更新。越权/不存在 NotFoundError。

    注意 embedding_model 用 `is not None`，支持传空串清空（与 I2 一致）。
    """
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
    if embedding_model is not None:
        cfg.embedding_model = embedding_model
    db.commit()
    db.refresh(cfg)
    return cfg


def delete_user_llm_config(db: Session, *, user_id, config_id) -> None:
    """删除指定 BYOK 配置。越权/不存在 NotFoundError。"""
    cfg = _get_owned_config(db, user_id=user_id, config_id=config_id)
    db.delete(cfg)
    db.commit()


def _get_owned_config(db: Session, *, user_id, config_id) -> UserLLMConfig:
    """查配置并校验归属。越权/不存在 NotFoundError（防探测，不泄露存在性）。

    与 resolve_llm_config 的 byok 分支共用 _get_user_config_by_id 的 NotFound 语义。
    """
    try:
        cid = uuid.UUID(config_id) if isinstance(config_id, str) else config_id
    except (ValueError, AttributeError):
        raise NotFoundError("LLM 配置不存在")
    cfg = db.get(UserLLMConfig, cid)
    if cfg is None or cfg.user_id != user_id:
        raise NotFoundError("LLM 配置不存在")
    return cfg


def config_to_dict(cfg: UserLLMConfig) -> dict:
    """BYOK 配置 → dict（key 掩码）。API 层和 service list 共用。"""
    return {
        "id": str(cfg.id),
        "name": cfg.name,
        "provider": cfg.provider,
        "base_url": cfg.base_url,
        "api_key_masked": _mask_key(decrypt_value(cfg.api_key_encrypted)),
        "model": cfg.model,
        "embedding_model": cfg.embedding_model,
    }


# ── 全局配置（管理员）──

def get_global_llm_settings(db: Session) -> dict:
    """获取全局 LLM 设置（掩码 key）。

    enabled 默认值与 _build_global_config 对齐：记录不存在时视为开启（True），
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
