"""MinerU 云端 PDF 解析 client（mineru.net 精准解析 API）。

将 PDF 转为结构化 Markdown（保留表格/标题/公式），替代 pypdf 纯文本提取，
用于知识库上传链路获得高质量分块输入。

API 流程（官方 OSS 直传模式，详见 https://mineru.net/apiManage/docs）：
  1. POST /file-urls/batch 获取 OSS 预签名直传链接
  2. PUT 上传 PDF bytes 到该链接
  3. 轮询 /extract-results/batch/{batch_id} 到 state=done
  4. 下载 full_zip_url，解压取 full.md

凭据三级 fallback（镜像 firecrawl_client）：全局 SystemSetting → env。无配置返回 None。
token 加密存储（Fernet），读取时脱敏。
"""

import io
import time
import zipfile
from dataclasses import dataclass

import httpx
from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import decrypt_value, encrypt_value
from app.models import SystemSetting

_DEFAULT_BASE_URL = "https://mineru.net"
_DEFAULT_MODEL_VERSION = "vlm"  # MinerU 推荐：高精度 VLM 模型
_POLL_INTERVAL = 3  # 轮询间隔（秒）
_POLL_TIMEOUT = 300  # 单任务最长等待（秒，约 100 页）
_HTTP_TIMEOUT = 60.0


@dataclass
class ResolvedMineruConfig:
    api_token: str
    base_url: str
    model_version: str
    source: str = "global"  # global / env


# ── 凭据解析 ─────────────────────────────────────────────────

def resolve_mineru_config(db: Session) -> ResolvedMineruConfig | None:
    """三级 fallback：全局 SystemSetting → env。无可用配置返回 None。

    全局条件：mineru_enabled.value.enabled is True AND
              mineru_config.value.api_token_encrypted 非空。
    """
    # 1) 全局 SystemSetting
    enabled_setting = db.scalar(
        select(SystemSetting).where(SystemSetting.key == "mineru_enabled")
    )
    if enabled_setting and enabled_setting.value.get("enabled") is True:
        cfg_setting = db.scalar(
            select(SystemSetting).where(SystemSetting.key == "mineru_config")
        )
        if cfg_setting and cfg_setting.value.get("api_token_encrypted"):
            api_token = decrypt_value(cfg_setting.value["api_token_encrypted"])
            base_url = cfg_setting.value.get("base_url") or _DEFAULT_BASE_URL
            model_version = cfg_setting.value.get("model_version") or _DEFAULT_MODEL_VERSION
            return ResolvedMineruConfig(
                api_token=api_token, base_url=base_url,
                model_version=model_version, source="global",
            )
    # 2) env 兜底
    s = _get_settings()
    if s.mineru_api_token:
        return ResolvedMineruConfig(
            api_token=s.mineru_api_token,
            base_url=s.mineru_base_url or _DEFAULT_BASE_URL,
            model_version=s.mineru_model_version or _DEFAULT_MODEL_VERSION,
            source="env",
        )
    return None


def _get_settings():
    from app.core.config import get_settings
    return get_settings()


def _mask_token(token: str) -> str:
    """token 脱敏（sk-****末尾）。"""
    if len(token) <= 8:
        return "****"
    return token[:3] + "****" + token[-4:]


# ── admin 配置 get/set ───────────────────────────────────────

def get_mineru_settings(db: Session) -> dict:
    """读全局配置（api_token 脱敏）。未配置时返回安全默认值。"""
    enabled_setting = db.scalar(
        select(SystemSetting).where(SystemSetting.key == "mineru_enabled")
    )
    cfg_setting = db.scalar(
        select(SystemSetting).where(SystemSetting.key == "mineru_config")
    )
    api_token_masked = ""
    if cfg_setting and cfg_setting.value.get("api_token_encrypted"):
        try:
            api_token_masked = _mask_token(
                decrypt_value(cfg_setting.value["api_token_encrypted"])
            )
        except Exception:
            api_token_masked = ""
    return {
        "enabled": bool(enabled_setting and enabled_setting.value.get("enabled")),
        "api_token_masked": api_token_masked,
        "base_url": cfg_setting.value.get("base_url", "") if cfg_setting else "",
        "model_version": cfg_setting.value.get("model_version", _DEFAULT_MODEL_VERSION) if cfg_setting else _DEFAULT_MODEL_VERSION,
    }


def set_mineru_settings(
    db: Session, *, enabled: bool, api_token: str = "",
    base_url: str | None = None, model_version: str | None = None,
) -> dict:
    """写全局配置。api_token 空串=不改（保留现有）。base_url/model_version 为 None=不改。"""
    # enabled 开关
    enabled_setting = db.scalar(
        select(SystemSetting).where(SystemSetting.key == "mineru_enabled")
    )
    if enabled_setting:
        enabled_setting.value = {"enabled": enabled}
    else:
        db.add(SystemSetting(key="mineru_enabled", value={"enabled": enabled}))

    # 配置详情
    cfg_setting = db.scalar(
        select(SystemSetting).where(SystemSetting.key == "mineru_config")
    )
    current = cfg_setting.value if cfg_setting else {}
    new_value = {
        "base_url": base_url if base_url is not None else current.get("base_url", _DEFAULT_BASE_URL),
        "model_version": model_version or current.get("model_version", _DEFAULT_MODEL_VERSION),
    }
    if api_token:
        new_value["api_token_encrypted"] = encrypt_value(api_token)
    elif current.get("api_token_encrypted"):
        new_value["api_token_encrypted"] = current["api_token_encrypted"]

    if cfg_setting:
        cfg_setting.value = new_value
    else:
        db.add(SystemSetting(key="mineru_config", value=new_value))
    db.commit()
    return get_mineru_settings(db)


# ── PDF 解析核心 ─────────────────────────────────────────────

def parse_pdf_to_markdown(
    db: Session, content: bytes, filename: str = "upload.pdf",
) -> str:
    """用 MinerU 云端 API 把 PDF bytes 转成 Markdown 字符串。

    流程：OSS 直传 → 轮询 → 下载 zip → 解压取 full.md。
    失败抛 RuntimeError（由调用方捕获，降级到 pypdf 或报错）。
    """
    cfg = resolve_mineru_config(db)
    if cfg is None:
        raise RuntimeError("MinerU 未配置（无 api_token）")

    headers = {
        "Authorization": f"Bearer {cfg.api_token}",
        "Content-Type": "application/json",
    }
    base = cfg.base_url.rstrip("/")

    # 1. 获取 OSS 直传链接（batch 接口，files 是对象数组）
    logger.info(f"MinerU: 获取 OSS 直传链接（{filename}, {len(content)} bytes）")
    resp = httpx.post(
        f"{base}/api/v4/file-urls/batch",
        headers=headers,
        json={"enable_formula": True, "enable_table": True, "language": "ch",
              "model_version": cfg.model_version,
              "files": [{"name": filename, "is_ocr": True}]},
        timeout=_HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    batch_data = resp.json().get("data", {})
    file_urls = batch_data.get("file_urls") or []
    batch_id = batch_data.get("batch_id")
    if not file_urls or not batch_id:
        raise RuntimeError(f"MinerU 获取直传链接失败：{resp.json()}")

    upload_url = file_urls[0]
    logger.info(f"MinerU: 上传到 OSS（batch_id={batch_id}）")
    put_resp = httpx.put(upload_url, content=content, timeout=_HTTP_TIMEOUT)
    put_resp.raise_for_status()

    # 2. 轮询结果（file-urls/batch 已创建任务，直接轮询 batch_id）
    logger.info(f"MinerU: 轮询任务结果（batch_id={batch_id}）")
    deadline = time.time() + _POLL_TIMEOUT
    while time.time() < deadline:
        r = httpx.get(
            f"{base}/api/v4/extract-results/batch/{batch_id}",
            headers=headers, timeout=_HTTP_TIMEOUT,
        )
        r.raise_for_status()
        result = r.json().get("data", {})
        results = result.get("extract_result") or []
        if results:
            item = results[0]
            state = item.get("state")
            if state == "done":
                zip_url = item.get("full_zip_url")
                if not zip_url:
                    raise RuntimeError(f"MinerU done 但无 full_zip_url：{item}")
                markdown = _download_and_extract_md(zip_url)
                logger.info(f"MinerU: 解析完成，markdown {len(markdown)} 字符")
                return markdown
            if state == "failed":
                err = item.get("err_msg", "未知错误")
                raise RuntimeError(f"MinerU 解析失败：{err}")
        time.sleep(_POLL_INTERVAL)
    raise RuntimeError(f"MinerU 轮询超时（{_POLL_TIMEOUT}s）")


def _download_and_extract_md(zip_url: str) -> str:
    """下载 zip，解压取 full.md 内容。"""
    resp = httpx.get(zip_url, timeout=_HTTP_TIMEOUT, follow_redirects=True)
    resp.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        # 优先找 full.md，找不到找任意 .md
        md_names = [n for n in zf.namelist() if n.endswith("full.md")] or \
                   [n for n in zf.namelist() if n.endswith(".md")]
        if not md_names:
            raise RuntimeError(f"MinerU zip 内无 markdown 文件：{zf.namelist()}")
        return zf.read(md_names[0]).decode("utf-8", errors="replace")
