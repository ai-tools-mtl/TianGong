from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ReviewRubric, Template

# 系统内置 Agent 技能定义（设计 7.4）。name/description/is_builtin 仅存在代码中。
BUILTIN_SKILLS = [
    {
        "skill_key": "rag_search",
        "name": "知识库检索",
        "description": "撰写/审查时检索用户知识库",
        "default_enabled": True,
    },
    {
        "skill_key": "rubric_review",
        "name": "Rubric 审查",
        "description": "按 Rubric 逐维度评分",
        "default_enabled": True,
    },
    {
        "skill_key": "consistency_check",
        "name": "自一致性校验",
        "description": "关键评分多次取均值",
        "default_enabled": True,
    },
    {
        "skill_key": "quality_report",
        "name": "质量报告",
        "description": "生成结构化审查报告",
        "default_enabled": True,
    },
    {
        "skill_key": "prior_art_hint",
        "name": "现有技术提示",
        "description": "撰写背景技术时提示检索方向（占位，检索在 P1）",
        "default_enabled": True,
    },
]

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


# 系统默认审查 Rubric（4 个维度）
DEFAULT_RUBRIC = [
    {
        "key": "completeness",
        "name": "内容完整性",
        "weight": 0.25,
        "scoring_guide": {
            "90-100": "所有必要章节填写完整，信息充分",
            "70-89": "大部分章节完整，个别章节信息不足",
            "50-69": "多个章节缺失或内容空洞",
            "0-49": "大量章节未填写",
        },
    },
    {
        "key": "solution_clarity",
        "name": "技术方案清晰度",
        "weight": 0.30,
        "scoring_guide": {
            "90-100": "技术方案清晰完整，含结构、流程、关键要素",
            "70-89": "方案基本清晰，部分要素不够明确",
            "50-69": "方案描述模糊，代理人难以理解",
            "0-49": "技术方案缺失或不可理解",
        },
    },
    {
        "key": "novelty",
        "name": "新颖性表述",
        "weight": 0.20,
        "scoring_guide": {
            "90-100": "明确指出与现有技术的区别",
            "70-89": "提到区别但对比不充分",
            "50-69": "未明确区别",
            "0-49": "完全未涉及新颖性",
        },
    },
    {
        "key": "writing_quality",
        "name": "撰写规范性",
        "weight": 0.25,
        "scoring_guide": {
            "90-100": "语言规范，逻辑清晰，格式统一",
            "70-89": "基本规范，少量表述问题",
            "50-69": "表述不够规范，需较多修改",
            "0-49": "语言混乱，难以理解",
        },
    },
]


def ensure_default_rubric(db: Session) -> ReviewRubric:
    """确保系统默认 Rubric 存在（幂等）。"""
    existing = db.scalar(select(ReviewRubric).where(ReviewRubric.scope == "system"))
    if existing:
        return existing
    rubric = ReviewRubric(
        scope="system", name="标准交底书评分标准",
        criteria=DEFAULT_RUBRIC, is_customized=False,
    )
    db.add(rubric)
    db.commit()
    db.refresh(rubric)
    return rubric
