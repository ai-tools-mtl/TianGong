"""LLM 配置服务：四级 Provider 解析 + 用户/全局配置管理（设计 8.4 + P2 env 兜底）。

优先级：用户自配(is_active=True) > 全局(SystemSetting) > env 兜底(glm_api_key 非空) > 返回 None
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import decrypt_value, encrypt_value
from app.models import SystemSetting, UserLLMConfig


@dataclass
class ResolvedLLMConfig:
    """解析后的生效配置。"""
    base_url: str
    api_key: str
    model: str
    embedding_model: str | None = None  # 新增（断链 A2 修复）
    source: str = "user"  # "user" / "global" / "env" / "admin"（admin 留待阶段 2）


def resolve_llm_config(db: Session, *, user_id) -> ResolvedLLMConfig | None:
    """三级优先级解析 LLM 配置：用户自配 > 全局 > env 兜底。

    env 兜底确保首次部署（admin 未配任何 Key）仍可用 AI。
    仅当 glm_api_key 非空时才兜底；否则返回 None（调用方报 no_llm_config）。
    """
    # ① 用户自配
    user_cfg = db.scalar(
        select(UserLLMConfig).where(
            (UserLLMConfig.user_id == user_id) & (UserLLMConfig.is_active.is_(True))
        )
    )
    if user_cfg:
        return ResolvedLLMConfig(
            base_url=user_cfg.base_url,
            api_key=decrypt_value(user_cfg.api_key_encrypted),
            model=user_cfg.model,
            embedding_model=user_cfg.embedding_model,
            source="user",
        )

    # ② 全局配置（llm_global_enabled=true 时）
    global_enabled = db.scalar(
        select(SystemSetting).where(SystemSetting.key == "llm_global_enabled")
    )
    if global_enabled and global_enabled.value.get("enabled"):
        global_cfg = db.scalar(
            select(SystemSetting).where(SystemSetting.key == "llm_global_config")
        )
        if global_cfg and global_cfg.value:
            v = global_cfg.value
            return ResolvedLLMConfig(
                base_url=v.get("base_url", ""),
                api_key=decrypt_value(v["api_key_encrypted"]) if v.get("api_key_encrypted") else "",
                model=v.get("model", ""),
                embedding_model=v.get("embedding_model"),
                source="global",
            )

    # ③ env 兜底（新增）：glm_api_key 非空时用 env 配置，
    #    保证首次部署（admin 尚未配置任何 Key）仍可使用 AI。
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

    # ④ 都没有
    return None


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
        "is_active": cfg.is_active,
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
        cfg.is_active = True
    else:
        cfg = UserLLMConfig(
            user_id=user_id, name=name, provider=provider, base_url=base_url,
            api_key_encrypted=encrypt_value(api_key), model=model,
            embedding_model=embedding_model, is_active=True,
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
        } if cfg else None,
    }


def set_global_llm_settings(
    db: Session, *, enabled: bool, base_url: str | None = None,
    api_key: str | None = None, model: str | None = None,
) -> dict:
    """管理员设置全局 LLM。"""
    # 开关
    setting = db.scalar(select(SystemSetting).where(SystemSetting.key == "llm_global_enabled"))
    if setting:
        setting.value = {"enabled": enabled}
    else:
        db.add(SystemSetting(key="llm_global_enabled", value={"enabled": enabled}))

    # 配置（只在提供新值时更新）
    if base_url or api_key or model:
        cfg = db.scalar(select(SystemSetting).where(SystemSetting.key == "llm_global_config"))
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
            db.add(SystemSetting(key="llm_global_config", value=new_value))

    db.commit()
    return get_global_llm_settings(db)


def _mask_key(key: str) -> str:
    """掩码 API key（sk-****abcd）。"""
    if len(key) <= 8:
        return "****"
    return key[:3] + "****" + key[-4:]
