import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ReviewRubric, Template

# 系统默认交底书模板的 8 章节。
# 写作指引（呼应现有技术缺点、结合附图阐述、提炼保护点等）沉淀在各章 SectionPrompt
# （section_prompts.py），title 只保留干净的短标题，UI 预览与 Word 导出更清爽。
DEFAULT_STRUCTURE = [
    {"id": "name", "order": 1, "key": "name", "title": "名称", "level": 1},
    {"id": "field", "order": 2, "key": "field", "title": "所属技术领域", "level": 1},
    {"id": "background", "order": 3, "key": "background", "title": "背景技术", "level": 1},
    {"id": "problem", "order": 4, "key": "problem", "title": "技术问题", "level": 1},
    {"id": "solution", "order": 5, "key": "solution", "title": "发明内容", "level": 1},
    {"id": "effect", "order": 6, "key": "effect", "title": "有益效果", "level": 1},
    {"id": "key_points", "order": 7, "key": "key_points", "title": "关键点与保护范围", "level": 1},
    {"id": "drawings", "order": 8, "key": "drawings", "title": "附图", "level": 1},
]


def _structure_signature(structure) -> str:
    """把章节结构序列化成稳定签名，用于检测默认模板是否需要升级。

    纳入 id/order/key/title/level 全字段——任何章节增删、改标题、改顺序都会让签名变化，
    从而触发覆盖更新。比离散版本号更可靠（不会忘记 bump），且零迁移。
    """
    norm = json.dumps(structure, ensure_ascii=False, sort_keys=True)
    return norm


def ensure_default_template(db: Session) -> Template:
    """确保系统默认模板存在且为最新结构（幂等）。

    - 不存在 → 新建
    - 存在但结构与 DEFAULT_STRUCTURE 不一致（章节增删/改标题/改顺序）→ 覆盖更新 structure
    - 存在且结构一致 → 直接返回

    注意：只更新模板本身，不迁移已建项目的 section 快照（设计 9.7 快照语义——
    老项目保持建项目时的章节结构，新建项目才用最新模板）。
    """
    existing = db.scalar(select(Template).where(Template.is_system.is_(True)))
    if existing:
        if _structure_signature(existing.structure) == _structure_signature(DEFAULT_STRUCTURE):
            return existing
        # 默认模板结构已升级（如章节增删/改标题），覆盖更新
        existing.structure = DEFAULT_STRUCTURE
        db.commit()
        db.refresh(existing)
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
