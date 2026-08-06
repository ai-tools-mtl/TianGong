"""腾讯 ima 检索源全局配置服务（admin 配置，所有用户共享单源）。

镜像 firecrawl_client / mineru_client 的全局配置模式：
- 配置存 SystemSetting，key = `ima_enabled`（开关）+ `ima_config`（凭据 JSON）。
- 凭据用 core.security 的 Fernet 加密（encrypt_value/decrypt_value）。
- resolve 优先级：全局 SystemSetting → env 兜底（ima_client_id/ima_api_key）→ None。

与用户级实现（已废弃）的差异：无 user_id，admin 单配置全局生效。
"""
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import decrypt_value, encrypt_value
from app.models import SystemSetting


@dataclass
class ResolvedIMAConfig:
    """解密后的 ima 凭据（运行时用，不持久化明文）。"""

    client_id: str
    api_key: str
    enabled: bool


# ── 凭据解析（检索时读）──

def resolve_ima_config(db: Session) -> ResolvedIMAConfig | None:
    """三级 fallback：全局 SystemSetting → env。无可用配置返回 None。

    全局条件：ima_enabled.value.enabled is True AND
              ima_config.value.client_id_encrypted/api_key_encrypted 非空。
    """
    # 1) 全局 SystemSetting
    enabled_setting = db.scalar(
        select(SystemSetting).where(SystemSetting.key == "ima_enabled")
    )
    if enabled_setting and enabled_setting.value.get("enabled") is True:
        cfg_setting = db.scalar(
            select(SystemSetting).where(SystemSetting.key == "ima_config")
        )
        if cfg_setting and cfg_setting.value.get("client_id_encrypted") and cfg_setting.value.get("api_key_encrypted"):
            try:
                return ResolvedIMAConfig(
                    client_id=decrypt_value(cfg_setting.value["client_id_encrypted"]),
                    api_key=decrypt_value(cfg_setting.value["api_key_encrypted"]),
                    enabled=True,
                )
            except Exception:
                # 解密失败（如 encryption_key 轮换后旧密文失效）——视为不可用
                pass
    # 2) env 兜底
    s = get_settings()
    if s.ima_client_id and s.ima_api_key:
        return ResolvedIMAConfig(
            client_id=s.ima_client_id, api_key=s.ima_api_key, enabled=True,
        )
    return None


# ── admin 配置 get/set ──

def get_ima_settings(db: Session) -> dict:
    """读全局配置（凭据脱敏）。未配置时返回安全默认值。"""
    enabled_setting = db.scalar(
        select(SystemSetting).where(SystemSetting.key == "ima_enabled")
    )
    cfg_setting = db.scalar(
        select(SystemSetting).where(SystemSetting.key == "ima_config")
    )
    client_id_masked = ""
    api_key_masked = ""
    if cfg_setting:
        try:
            if cfg_setting.value.get("client_id_encrypted"):
                client_id_masked = _mask_id(decrypt_value(cfg_setting.value["client_id_encrypted"]))
            if cfg_setting.value.get("api_key_encrypted"):
                api_key_masked = _mask_key(decrypt_value(cfg_setting.value["api_key_encrypted"]))
        except Exception:
            client_id_masked = api_key_masked = ""
    return {
        "enabled": bool(enabled_setting and enabled_setting.value.get("enabled")),
        "client_id_masked": client_id_masked,
        "api_key_masked": api_key_masked,
    }


def set_ima_settings(
    db: Session, *,
    enabled: bool,
    client_id: str = "",
    api_key: str = "",
    updated_by=None,
) -> None:
    """upsert 全局配置。

    - enabled：总是写。
    - client_id / api_key 空串表示不修改现有（保留）。
    - 仅当 client_id 或 api_key 至少一项被显式提供时，才写 ima_config 行。
    """
    # 1) enabled 开关
    enabled_setting = db.scalar(
        select(SystemSetting).where(SystemSetting.key == "ima_enabled")
    )
    if enabled_setting:
        enabled_setting.value = {"enabled": enabled}
    else:
        db.add(SystemSetting(
            key="ima_enabled", value={"enabled": enabled}, updated_by=updated_by,
        ))

    # 2) config 行（client_id / api_key）
    if client_id or api_key:
        cfg_setting = db.scalar(
            select(SystemSetting).where(SystemSetting.key == "ima_config")
        )
        current = cfg_setting.value if cfg_setting else {}
        new_value = {}
        # client_id：显式提供则覆盖，否则保留已有
        if client_id:
            new_value["client_id_encrypted"] = encrypt_value(client_id)
        elif current.get("client_id_encrypted"):
            new_value["client_id_encrypted"] = current["client_id_encrypted"]
        # api_key：同上
        if api_key:
            new_value["api_key_encrypted"] = encrypt_value(api_key)
        elif current.get("api_key_encrypted"):
            new_value["api_key_encrypted"] = current["api_key_encrypted"]
        if cfg_setting:
            cfg_setting.value = new_value
        else:
            db.add(SystemSetting(
                key="ima_config", value=new_value, updated_by=updated_by,
            ))
    db.commit()


# ── 掩码（client_id 较短，保守遮；api_key 同 firecrawl 规则）──

def _mask_key(key: str) -> str:
    """掩码 api key（前3 + **** + 后4）。短 key 全遮。"""
    if len(key) <= 8:
        return "****"
    return key[:3] + "****" + key[-4:]


def _mask_id(client_id: str) -> str:
    """掩码 client id。client_id 通常较短，保留首2尾2。"""
    if len(client_id) <= 4:
        return "****"
    return client_id[:2] + "****" + client_id[-2:]
