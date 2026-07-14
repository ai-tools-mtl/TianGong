"""技能开关服务（设计 7.4）：builtin 定义 + 项目覆盖。"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import ValidationError
from app.models import AgentSkill
from app.services.seed_service import BUILTIN_SKILLS

# 索引化便于查询
_BUILTIN_BY_KEY = {s["skill_key"]: s for s in BUILTIN_SKILLS}


def list_skills(db: Session, *, project_id) -> list[dict]:
    """返回项目下所有技能：builtin LEFT JOIN 项目覆盖行。

    缺行 = 用 builtin 默认值（enabled=default_enabled, is_overridden=False）。
    """
    pid = project_id
    overrides = {
        row.skill_key: row
        for row in db.scalars(
            select(AgentSkill).where(AgentSkill.project_id == pid)
        )
    }
    result = []
    for builtin in BUILTIN_SKILLS:
        key = builtin["skill_key"]
        row = overrides.get(key)
        if row is not None:
            enabled = row.enabled
            config = row.config
            is_overridden = True
        else:
            enabled = builtin["default_enabled"]
            config = None
            is_overridden = False
        result.append({
            "skill_key": key,
            "name": builtin["name"],
            "description": builtin["description"],
            "enabled": enabled,
            "config": config,
            "is_builtin": True,
            "is_overridden": is_overridden,
        })
    return result


def is_skill_enabled(db: Session, *, project_id, skill_key: str) -> bool:
    """单个技能是否启用。未知 key 视为默认 True（不阻断主流程）。"""
    if skill_key not in _BUILTIN_BY_KEY:
        return True
    row = db.scalar(
        select(AgentSkill).where(
            AgentSkill.project_id == project_id,
            AgentSkill.skill_key == skill_key,
        )
    )
    if row is None:
        return _BUILTIN_BY_KEY[skill_key]["default_enabled"]
    return row.enabled


def set_skill(
    db: Session, *, project_id, skill_key: str, enabled: bool, config: dict | None = None,
) -> AgentSkill:
    """设置项目级技能开关（幂等：存在则更新，不存在则创建）。"""
    if skill_key not in _BUILTIN_BY_KEY:
        raise ValidationError(f"未知技能：{skill_key}")
    row = db.scalar(
        select(AgentSkill).where(
            AgentSkill.project_id == project_id,
            AgentSkill.skill_key == skill_key,
        )
    )
    if row is None:
        row = AgentSkill(
            project_id=project_id, skill_key=skill_key,
            enabled=enabled, config=config,
        )
        db.add(row)
    else:
        row.enabled = enabled
        row.config = config
    db.commit()
    db.refresh(row)
    return row
