"""腾讯 ima 检索源凭据服务（单配置语义）。

与 llm_config_service 的差异：ima 是单账号单源，一个用户只存一条配置，
无多配置 CRUD；通过 enabled 开关控制是否参与检索。

复用 core.security 的 Fernet 加密（encrypt_value/decrypt_value），
与 UserLLMConfig 的凭据加密链路一致。

resolve_ima_config 返回 ResolvedIMAConfig（解密后的明文，供检索客户端使用），
未配置 / enabled=False 时返回 None（调用方据此跳过 ima 检索）。
"""
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import ValidationError
from app.core.security import decrypt_value, encrypt_value
from app.models import UserIMAConfig


@dataclass
class ResolvedIMAConfig:
    """解密后的 ima 凭据（运行时用，不持久化明文）。"""

    client_id: str
    api_key: str
    enabled: bool


# ── 单配置 upsert / 读取 ──

def upsert_ima_config(
    db: Session, *, user_id,
    client_id: str | None = None,
    api_key: str | None = None,
    enabled: bool | None = None,
    name: str | None = None,
) -> UserIMAConfig:
    """新增或更新当前用户的 ima 配置（单配置语义）。

    client_id / api_key 传 None 或空串表示不改（留空=不改，与 LLM 配置一致）。
    enabled / name 显式传入才更新。新建时 client_id / api_key 必须都给。
    """
    cfg = db.scalar(select(UserIMAConfig).where(UserIMAConfig.user_id == user_id))
    if cfg is None:
        # 新建：凭据必填
        if not client_id or not api_key:
            raise ValidationError("首次配置必须同时提供 client_id 和 api_key")
        cfg = UserIMAConfig(
            user_id=user_id,
            name=name or "我的 ima",
            client_id_encrypted=encrypt_value(client_id),
            api_key_encrypted=encrypt_value(api_key),
            enabled=enabled if enabled is not None else False,
        )
        db.add(cfg)
    else:
        # 更新：仅提供才改
        if client_id:
            cfg.client_id_encrypted = encrypt_value(client_id)
        if api_key:
            cfg.api_key_encrypted = encrypt_value(api_key)
        if enabled is not None:
            cfg.enabled = enabled
        if name is not None:
            cfg.name = name
    db.commit()
    db.refresh(cfg)
    return cfg


def get_ima_config(db: Session, *, user_id) -> UserIMAConfig | None:
    """读取当前用户的 ima 配置（ORM 对象，未解密）。无则 None。"""
    return db.scalar(select(UserIMAConfig).where(UserIMAConfig.user_id == user_id))


def resolve_ima_config(db: Session, *, user_id) -> ResolvedIMAConfig | None:
    """解析出可用于检索的 ima 凭据。

    返回条件：配置存在 **且** enabled=True **且** 凭据非空。
    否则返回 None（调用方据此跳过 ima 检索，不影响本地 RAG）。
    """
    cfg = get_ima_config(db, user_id=user_id)
    if cfg is None or not cfg.enabled:
        return None
    try:
        client_id = decrypt_value(cfg.client_id_encrypted)
        api_key = decrypt_value(cfg.api_key_encrypted)
    except Exception:
        # 解密失败（如 encryption_key 轮换后旧密文失效）——视为不可用，不阻断检索
        return None
    if not client_id or not api_key:
        return None
    return ResolvedIMAConfig(client_id=client_id, api_key=api_key, enabled=True)


def config_to_dict(cfg: UserIMAConfig | None) -> dict:
    """配置 → dict（凭据掩码）。无配置时返回 {configured: False, enabled: False}。

    给前端展示用：不回显明文，client_id 取首尾，api_key 同 LLM 的 _mask_key 规则。
    """
    if cfg is None:
        return {"configured": False, "enabled": False, "name": "", "client_id_masked": "", "api_key_masked": ""}
    return {
        "configured": True,
        "enabled": cfg.enabled,
        "name": cfg.name,
        "client_id_masked": _mask_id(decrypt_value(cfg.client_id_encrypted)),
        "api_key_masked": _mask_key(decrypt_value(cfg.api_key_encrypted)),
    }


# ── 掩码（与 llm_config_service 同构，独立实现避免跨模块私有依赖）──

def _mask_key(key: str) -> str:
    """掩码 api key（前3 + **** + 后4）。短 key 全遮。"""
    if len(key) <= 8:
        return "****"
    return key[:3] + "****" + key[-4:]


def _mask_id(client_id: str) -> str:
    """掩码 client id。client_id 通常较短，保守遮一半。"""
    if len(client_id) <= 4:
        return "****"
    # 保留前2后2，中间遮蔽
    return client_id[:2] + "****" + client_id[-2:]
