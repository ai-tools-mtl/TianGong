"""全局 LLM 账户余额探测与低额告警（优化计划批次 2b）。

DeepSeek 提供 GET /user/balance（OpenAI 系无公开等价端点）。admin 在 console
手动触发「立即探测」，结果落 SystemSetting llm_balance_status，前端据此渲染横幅：
低于阈值红、探测失败黄、不支持/未配置灰。

设计决策（计划 D2 去范围项）：不做后台自动轮询——涉及后台任务生命周期管理，
内测期 admin 手动探测够用；将来自动化必须带 TIANGONG_TESTING 跳过守卫。
"""

from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import SystemSetting

BALANCE_STATUS_KEY = "llm_balance_status"
BALANCE_THRESHOLD_KEY = "llm_balance_threshold"
DEFAULT_THRESHOLD = 10.0  # CNY

# 余额查询是轻请求，3s 足够；手动触发失败可再点，不做重试
_PROBE_TIMEOUT = 3.0


def _result(**kw) -> dict:
    base = {
        "supported": True,
        "status": "ok",  # ok | low | error | unsupported | unconfigured
        "provider": "deepseek",
        "amount": None,
        "currency": "CNY",
        "threshold": None,
        "is_low": False,
        "probed_at": datetime.now(timezone.utc).isoformat(),
        "error": None,
    }
    base.update(kw)
    return base


def _detect_deepseek(base_url: str) -> bool:
    """全局配置无 provider 字段，按 base_url 判定（api.deepseek.com）。"""
    return "deepseek" in (base_url or "").lower()


def _parse_balance(data: dict) -> float:
    """解析 DeepSeek /user/balance 响应：{is_available, balance_infos: [...]}。

    取 CNY 条目的 total_balance；无 CNY 取第一条。结构不符抛 ValueError。
    注：响应结构按 DeepSeek 文档实现，上线前用真实 key curl 验证一次
    （计划批次 2 标注的待验证项）。
    """
    infos = data.get("balance_infos") or []
    if not infos:
        raise ValueError("balance_infos 为空")
    entry = next((i for i in infos if i.get("currency") == "CNY"), infos[0])
    return float(entry["total_balance"])


def _probe_deepseek(base_url: str, api_key: str, threshold: float) -> dict:
    url = base_url.rstrip("/") + "/user/balance"
    try:
        resp = httpx.get(url, headers={"Authorization": f"Bearer {api_key}"},
                         timeout=_PROBE_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except httpx.TimeoutException:
        return _result(status="error", threshold=threshold, error="探测超时（服务不可达）")
    except httpx.HTTPStatusError as e:
        code = e.response.status_code
        hint = "API Key 无效" if code in (401, 403) else f"HTTP {code}"
        return _result(status="error", threshold=threshold, error=f"探测失败：{hint}")
    except Exception as e:  # noqa: BLE001 — 降级点：网络层任何异常都转错误状态，不抛
        return _result(status="error", threshold=threshold,
                       error=f"探测失败：{e.__class__.__name__}")
    try:
        amount = _parse_balance(data)
    except Exception:  # noqa: BLE001 — 解析失败同样转错误状态
        return _result(status="error", threshold=threshold,
                       error="响应解析失败（DeepSeek 接口结构可能已变更）")
    is_low = amount < threshold
    return _result(status="low" if is_low else "ok", amount=amount,
                   threshold=threshold, is_low=is_low)


def _save_status(db: Session, result: dict) -> None:
    setting = db.scalar(select(SystemSetting).where(SystemSetting.key == BALANCE_STATUS_KEY))
    if setting:
        setting.value = result
    else:
        db.add(SystemSetting(key=BALANCE_STATUS_KEY, value=result))
    db.commit()


def get_threshold(db: Session) -> float:
    s = db.scalar(select(SystemSetting).where(SystemSetting.key == BALANCE_THRESHOLD_KEY))
    if s and s.value and isinstance(s.value, dict):
        try:
            return float(s.value.get("threshold", DEFAULT_THRESHOLD))
        except (TypeError, ValueError):
            pass
    return DEFAULT_THRESHOLD


def set_threshold(db: Session, *, threshold: float) -> float:
    """设置低额阈值（CNY）。负数拒绝。"""
    if threshold < 0:
        from app.core.exceptions import ValidationError
        raise ValidationError("阈值不能为负数")
    setting = db.scalar(select(SystemSetting).where(SystemSetting.key == BALANCE_THRESHOLD_KEY))
    value = {"threshold": threshold}
    if setting:
        setting.value = value
    else:
        db.add(SystemSetting(key=BALANCE_THRESHOLD_KEY, value=value))
    db.commit()
    return threshold


def get_last_status(db: Session) -> dict | None:
    s = db.scalar(select(SystemSetting).where(SystemSetting.key == BALANCE_STATUS_KEY))
    return s.value if s and s.value else None


def probe_balance(db: Session) -> dict:
    """探测全局 chat 配置的账户余额，结果落库并返回。

    - 全局未配置/未启用 → supported=False, status="unconfigured"
    - 非 deepseek provider → supported=False, status="unsupported"（OpenAI 系无
      公开余额端点，不硬造）
    - 探测异常 → status="error"（落库，前端黄横幅）
    - 成功 → status="ok"；金额 < 阈值 → "low"（前端红横幅）
    """
    from app.services.llm_config_service import _build_global_chat_config

    threshold = get_threshold(db)
    cfg = _build_global_chat_config(db, source="global")
    if cfg is None:
        result = _result(supported=False, status="unconfigured", threshold=threshold)
    elif not _detect_deepseek(cfg.base_url):
        result = _result(supported=False, status="unsupported", threshold=threshold)
    else:
        result = _probe_deepseek(cfg.base_url, cfg.api_key, threshold)
    _save_status(db, result)
    return result
