"""G3 rerank 配置 service（spec §5.3, D6）。

镜像 embedding 配置的 global 解析模式（rerank 暂不做用户级 BYOK，简化）。
配置存 SystemSetting key='rag_rerank_config'。
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import encrypt_value, decrypt_value
from app.models import SystemSetting
from app.rag.reranker import RerankConfig

RERANK_SETTING_KEY = "rag_rerank_config"


def get_global_rerank_settings(db: Session) -> dict:
    """读取全局 rerank 配置（api_key 返回 _encrypted 后缀，不返回明文）。"""
    setting = db.execute(
        select(SystemSetting).where(SystemSetting.key == RERANK_SETTING_KEY)
    ).scalar_one_or_none()
    if not setting:
        return {"enabled": False, "base_url": "", "api_key_encrypted": "", "model": ""}
    return dict(setting.value)


def set_global_rerank_settings(
    db: Session, *, enabled: bool, base_url: str, api_key: str, model: str
) -> None:
    """upsert 全局 rerank 配置（api_key 加密存储）。"""
    value = {
        "enabled": enabled,
        "base_url": base_url,
        "api_key_encrypted": encrypt_value(api_key) if api_key else "",
        "model": model,
    }
    setting = db.execute(
        select(SystemSetting).where(SystemSetting.key == RERANK_SETTING_KEY)
    ).scalar_one_or_none()
    if setting:
        setting.value = value
    else:
        db.add(SystemSetting(key=RERANK_SETTING_KEY, value=value))
    db.commit()


def resolve_rerank_config(db: Session, *, user_id) -> RerankConfig:
    """解析 rerank 配置（global only，不做 user 级）。

    返回 RerankConfig。enabled=False 表示关闭（不返回 None，调用方无需判空）。
    """
    settings = get_global_rerank_settings(db)
    if not settings.get("base_url"):
        return RerankConfig(enabled=False, base_url="", api_key="", model="")
    api_key = decrypt_value(settings["api_key_encrypted"]) if settings.get("api_key_encrypted") else ""
    return RerankConfig(
        enabled=bool(settings.get("enabled")),
        base_url=settings["base_url"],
        api_key=api_key,
        model=settings.get("model", ""),
    )
