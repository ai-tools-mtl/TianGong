from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Template

# 系统默认交底书模板的 8 章节
DEFAULT_STRUCTURE = [
    {"id": "name", "order": 1, "key": "name", "title": "发明名称", "level": 1},
    {"id": "field", "order": 2, "key": "field", "title": "技术领域", "level": 1},
    {"id": "background", "order": 3, "key": "background", "title": "背景技术", "level": 1},
    {"id": "problem", "order": 4, "key": "problem", "title": "发明目的与技术问题", "level": 1},
    {"id": "solution", "order": 5, "key": "solution", "title": "技术方案", "level": 1},
    {"id": "effect", "order": 6, "key": "effect", "title": "有益效果", "level": 1},
    {"id": "drawings", "order": 7, "key": "drawings", "title": "附图说明", "level": 1},
    {"id": "embodiment", "order": 8, "key": "embodiment", "title": "具体实施方式", "level": 1},
]


def ensure_default_template(db: Session) -> Template:
    """确保系统默认模板存在（幂等）。应用启动时调用。"""
    existing = db.scalar(select(Template).where(Template.is_system.is_(True)))
    if existing:
        return existing
    tpl = Template(
        name="标准交底书模板",
        structure=DEFAULT_STRUCTURE,
        is_system=True,
        is_default=True,
    )
    db.add(tpl)
    db.commit()
    db.refresh(tpl)
    return tpl
