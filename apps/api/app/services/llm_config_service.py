"""LLM 配置服务：按 source 解析 LLM 配置 + 用户/全局配置管理（P2 白名单授权模型）。

source 取值：
- "global"：全局 Key（admin 免授权；非 admin 须有有效 grant）
- "byok:{config_id}"：用户自配的指定配置（校验归属，越权 NotFound）
- "env"：env 兜底
- None（临时 fallback，Task 4.0 前端传 source 后可移除）：
  admin → global；非 admin → 若被授权则 global，否则单条 BYOK，否则 env，否则 None
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
    - None（临时 fallback，Task 4.0 前端传 source 后可移除）：
      admin → global；非 admin → 若被授权则 global，否则单条 BYOK，否则 env，否则 None
    """
    user = db.get(User, user_id)

    # ---- source=None 临时 fallback（Task 4.0 后移除）----
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
    """临时 fallback（Task 4.0 前端传 source 后移除）。

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

    # 单条 BYOK（过渡：用户可能有多条，取第一条；Task 2.3/4.0 后由 source 指定）
    user_cfg = db.scalar(select(UserLLMConfig).where(UserLLMConfig.user_id == user_id))
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
    """从 SystemSetting 构造全局配置。全局未配返回 None。"""
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


# ── 用户 BYOK ──

def get_user_llm_config(db: Session, *, user_id) -> dict | None:
    """获取用户 LLM 配置（掩码 key）。"""
    cfg = db.scalar(select(UserLLMConfig).where(UserLLMConfig.user_id == user_id))
    if not cfg:
        return None
    return {
        "provider": cfg.provider,
        "base_url": cfg.base_url,
        "api_key_masked": _mask_key(decrypt_value(cfg.api_key_encrypted)),
        "model": cfg.model,
        "embedding_model": cfg.embedding_model,
    }


def set_user_llm_config(
    db: Session, *, user_id, provider: str, base_url: str,
    api_key: str, model: str, embedding_model: str | None = None,
    name: str = "default",
) -> UserLLMConfig:
    """设置/更新用户 LLM 配置。

    P2 过渡态：user_id 已去 unique，一个用户可有多条配置。本函数沿用旧
    「find-one-or-create」语义——命中时更新第一条匹配行，否则新建。
    多行场景的正式拆分（list/具名更新）见 Task 2.3。当前多数测试/接口
    仍按单配置使用，默认 name="default"。
    """
    cfg = db.scalar(select(UserLLMConfig).where(UserLLMConfig.user_id == user_id))
    if cfg:
        cfg.name = name
        cfg.provider = provider
        cfg.base_url = base_url
        cfg.api_key_encrypted = encrypt_value(api_key)
        cfg.model = model
        cfg.embedding_model = embedding_model
    else:
        cfg = UserLLMConfig(
            user_id=user_id, name=name, provider=provider, base_url=base_url,
            api_key_encrypted=encrypt_value(api_key), model=model,
            embedding_model=embedding_model,
        )
        db.add(cfg)
    db.commit()
    db.refresh(cfg)
    return cfg


def delete_user_llm_config(db: Session, *, user_id) -> None:
    cfg = db.scalar(select(UserLLMConfig).where(UserLLMConfig.user_id == user_id))
    if cfg:
        db.delete(cfg)
        db.commit()


# ── 全局配置（管理员）──

def get_global_llm_settings(db: Session) -> dict:
    """获取全局 LLM 设置（掩码 key）。"""
    enabled = db.scalar(select(SystemSetting).where(SystemSetting.key == "llm_global_enabled"))
    cfg = db.scalar(select(SystemSetting).where(SystemSetting.key == "llm_global_config"))
    return {
        "llm_global_enabled": enabled.value.get("enabled", True) if enabled else False,
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

    # 配置：有任一字段提供则更新（含 allowed_models 显式提供空 list 的清空场景）
    if base_url or api_key or model or embedding_model or allowed_models is not None:
        cfg = db.scalar(select(SystemSetting).where(SystemSetting.key == "llm_global_config"))
        current = cfg.value if cfg else {}
        new_value = {
            "base_url": base_url or current.get("base_url", ""),
            "model": model or current.get("model", ""),
        }
        # embedding_model: 提供则更新，否则保留现有（补断链 A2：get 分支读但 set 从不写）
        if embedding_model:
            new_value["embedding_model"] = embedding_model
        elif current.get("embedding_model"):
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
