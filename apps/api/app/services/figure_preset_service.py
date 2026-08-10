"""专利附图风格预设服务。

管理 admin 对内置预设的微调（覆盖）。3 个预设（patent-bw/clean-color/technical）
在 app.ai.figure_presets.STYLE_PRESETS 内置定义，admin 可通过 SystemSetting 微调
部分参数（如 line_width/font_size/scale/border），不能增删预设。

存储模式照 ima_config_service：单行 SystemSetting（key=figure_style_presets），
value 是 {preset_id: {overridden_field: value, ...}} 的 overrides dict。
读取时与内置默认深合并（overrides 覆盖内置）。无加密（预设不含敏感信息）。
"""
from __future__ import annotations

import copy

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.figure_presets import STYLE_PRESETS
from app.models import SystemSetting

FIGURE_PRESETS_KEY = "figure_style_presets"

# 允许 admin 微调的字段白名单（防止任意覆盖破坏预设结构）
_TUNABLE_FIELDS = {"font_family", "font_size", "line_width"}


def _deep_merge(base: dict, overrides: dict) -> dict:
    """深合并：overrides 的值覆盖 base 同路径的值（递归到 render dict）。"""
    result = copy.deepcopy(base)
    for k, v in (overrides or {}).items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def get_figure_presets(db: Session) -> dict:
    """读取 3 个预设的生效参数（内置默认 + admin 微调深合并）。

    返回 {preset_id: {label, colors, font_family, ..., render: {scale, border}, id}}。
    """
    setting = db.scalar(select(SystemSetting).where(SystemSetting.key == FIGURE_PRESETS_KEY))
    all_overrides = setting.value if setting and setting.value else {}

    presets = {}
    for sid, base in STYLE_PRESETS.items():
        merged = _deep_merge(base, all_overrides.get(sid, {}))
        merged["id"] = sid
        presets[sid] = merged
    return presets


def set_figure_preset(
    db: Session, *, preset_id: str, overrides: dict, updated_by=None,
) -> dict:
    """微调单个预设。overrides 仅白名单字段（_TUNABLE_FIELDS）生效，其余忽略。

    存储结构：SystemSetting.value = {preset_id: {field: value}}。
    """
    if preset_id not in STYLE_PRESETS:
        from app.core.exceptions import ValidationError
        raise ValidationError(f"未知预设: {preset_id}")

    # 仅保留白名单字段
    clean = {k: v for k, v in overrides.items() if k in _TUNABLE_FIELDS}

    setting = db.scalar(select(SystemSetting).where(SystemSetting.key == FIGURE_PRESETS_KEY))
    current = setting.value if setting and setting.value else {}
    preset_overrides = dict(current.get(preset_id, {}))
    preset_overrides.update(clean)
    current[preset_id] = preset_overrides

    if setting:
        setting.value = current
    else:
        db.add(SystemSetting(key=FIGURE_PRESETS_KEY, value=current, updated_by=updated_by))
    db.commit()
    return get_figure_presets(db)[preset_id]
