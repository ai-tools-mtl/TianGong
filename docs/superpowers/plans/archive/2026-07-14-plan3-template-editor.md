# 计划 3：模板与编辑器 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** 实现模板模块（Word 上传→异步解析→模板管理）+ 章节数据模型 + Tiptap 富文本编辑器 + 项目详情页（章节列表 + 编辑器），产出"创建项目→进入编辑→逐章节撰写"的完整闭环。

**Architecture:** 后端新增 Template/ParseJob/Section 三个模型 + python-docx 解析器（含 NumberingResolver）+ 异步解析任务 + 模板/章节 CRUD API。前端集成 Tiptap v2 编辑器 + 项目详情页（左侧大纲 + 中间编辑器）。章节内容存 Tiptap JSON。

**Tech Stack:** python-docx + lxml（Word 解析）· FastAPI BackgroundTasks（异步）· Tiptap v2 + @tiptap/react（富文本）· Starkit（章节状态机前端呈现）

**Spec reference:** 设计文档 v1.5
- 数据模型：3.2 Template / ParseJob / Section
- 模板模块：第 9 章（9.1 流程 / 9.6 编号解析 / 9.7 模板变更语义）
- 章节流程：2.2（严格顺序 / 纯手写路径）
- 富文本：Tiptap + JSON（3.3 决策 1）
- 模板与项目解耦：9.7（创建时快照）

**Gotchas 参考:** G2（JSONB sqlite 兼容）· G4（邮箱校验，创建模板不涉及）

---

## 后端 API 设计（本计划新增）

| 端点 | 方法 | 说明 | 认证 |
|---|---|---|---|
| `/api/v1/templates` | GET | 列出我的模板 + 系统默认 | 是 |
| `/api/v1/templates` | POST | 上传 Word 创建模板（multipart） | 是 |
| `/api/v1/templates/{id}` | GET | 模板详情（含 structure/styles） | 是 |
| `/api/v1/templates/{id}` | DELETE | 删除模板（系统模板除外） | 是 |
| `/api/v1/templates/{id}/default` | POST | 设为默认 | 是 |
| `/api/v1/parse-jobs/{id}` | GET | 查询解析任务状态 | 是 |
| `/api/v1/projects/{id}/sections` | GET | 列出项目章节 | 是 |
| `/api/v1/sections/{id}` | GET | 章节详情（含 content） | 是 |
| `/api/v1/sections/{id}` | PATCH | 更新章节内容/状态 | 是 |

---

## 文件结构（本计划新增/修改）

```
apps/api/
├── app/
│   ├── models/
│   │   ├── template.py          # 新增：Template 模型
│   │   ├── parse_job.py         # 新增：ParseJob 模型
│   │   └── section.py           # 新增：Section 模型
│   ├── schemas/
│   │   ├── template.py          # 新增
│   │   └── section.py           # 新增
│   ├── services/
│   │   ├── template_service.py  # 新增：模板 CRUD
│   │   ├── section_service.py   # 新增：章节 CRUD + 顺序控制
│   │   └── parse_service.py     # 新增：解析编排
│   ├── parsing/                 # 新增：Word 解析器
│   │   ├── __init__.py
│   │   ├── structure_extractor.py   # 章节结构（Heading 样式）
│   │   ├── style_extractor.py       # 样式（继承解析 + eastAsia）
│   │   ├── numbering_resolver.py    # 自动编号（numbering.xml 计数器）
│   │   └── docx_parser.py           # 编排：调用上面三个 + 正则兜底
│   ├── api/
│   │   ├── templates.py         # 新增
│   │   └── sections.py          # 新增
│   └── ...（已有文件修改：models/__init__, router, project_service 创建项目时生成 sections）
├── uploads/                     # 上传的 Word 文件（.gitignore）
└── tests/
    ├── test_parsing.py          # 解析器单元测试
    ├── test_templates.py        # 模板 API
    └── test_sections.py         # 章节 API + 顺序控制

apps/web/
└── src/
    ├── components/
    │   ├── editor/
    │   │   ├── tiptap-editor.tsx     # Tiptap 编辑器封装
    │   │   └── toolbar.tsx           # 工具栏（加粗/列表/标题...）
    │   ├── section-outline.tsx       # 左侧章节大纲
    │   └── template-manager.tsx      # 模板管理（上传/列表）
    ├── app/(app)/
    │   ├── projects/[id]/
    │   │   └── page.tsx              # 项目详情页（大纲+编辑器）
    │   └── templates/
    │       └── page.tsx              # 模板管理页
    └── lib/queries.ts                # 修改：加 templates/sections hooks
```

---

## 任务 0：数据模型（Template / ParseJob / Section）+ 迁移

**Files:**
- Create: `apps/api/app/models/template.py`
- Create: `apps/api/app/models/parse_job.py`
- Create: `apps/api/app/models/section.py`
- Modify: `apps/api/app/models/__init__.py`
- Modify: `apps/api/app/models/project.py`（template_id 改为真外键）
- Test: `apps/api/tests/test_models.py`（追加）

- [ ] **Step 1: 实现 Template 模型**

Create `apps/api/app/models/template.py`:
```python
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin

# JSON 兼容类型（生产 JSONB，sqlite 测试降级 JSON）
from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB
_JSONType = JSONB().with_variant(JSON, "sqlite")


class Template(Base, IdMixin, TimestampMixin):
    __tablename__ = "templates"

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    source_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    structure: Mapped[list] = mapped_column(_JSONType)   # TemplateSection 数组
    styles: Mapped[dict | None] = mapped_column(_JSONType, nullable=True)
    numbering: Mapped[dict | None] = mapped_column(_JSONType, nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
```

- [ ] **Step 2: 实现 ParseJob 模型**

Create `apps/api/app/models/parse_job.py`:
```python
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin


class ParseJob(Base, IdMixin, TimestampMixin):
    __tablename__ = "parse_jobs"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("templates.id", ondelete="SET NULL"), nullable=True
    )
    source_path: Mapped[str] = mapped_column(String(512))
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending/processing/completed/failed
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

- [ ] **Step 3: 实现 Section 模型**

Create `apps/api/app/models/section.py`:
```python
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin
from app.models.project import _JSONType  # 复用 JSON 兼容类型


class Section(Base, IdMixin, TimestampMixin):
    __tablename__ = "sections"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    template_section_id: Mapped[str] = mapped_column(String(100))
    order: Mapped[int] = mapped_column(Integer)
    key: Mapped[str] = mapped_column(String(50))  # name/field/background/.../custom
    title: Mapped[str] = mapped_column(String(255))
    content: Mapped[dict | None] = mapped_column(_JSONType, nullable=True)  # Tiptap JSON
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="empty")  # empty/drafting/confirmed
```

- [ ] **Step 4: 把 _JSONType 提取到可复用位置**

把 `apps/api/app/models/project.py` 里的 `_JSONType` 定义改为模块级，然后 section.py / template.py 从 project 导入（或移到 base.py）。为避免循环导入，移到 `base.py`:

Modify `apps/api/app/models/base.py` 末尾追加:
```python
from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB

# 生产用 JSONB，sqlite 测试降级为 JSON
JSONType = JSONB().with_variant(JSON, "sqlite")
```

然后 project.py / template.py / section.py 改为 `from app.models.base import JSONType` 并用它替换各自的 `_JSONType`。

- [ ] **Step 5: project.py 的 template_id 改为真外键**

Modify `apps/api/app/models/project.py`，把 `template_id` 改为:
```python
template_id: Mapped[uuid.UUID | None] = mapped_column(
    ForeignKey("templates.id", ondelete="SET NULL"), nullable=True
)
```

- [ ] **Step 6: 更新 models/__init__.py**

```python
from app.models.base import Base, JSONType
from app.models.parse_job import ParseJob
from app.models.project import Project
from app.models.section import Section
from app.models.system_setting import SystemSetting
from app.models.template import Template
from app.models.user import User

__all__ = ["Base", "JSONType", "User", "Project", "SystemSetting", "Template", "ParseJob", "Section"]
```

- [ ] **Step 7: 追加模型测试**

在 `apps/api/tests/test_models.py` 追加:
```python
def test_template_defaults():
    from app.models import Template
    t = Template(name="测试模板", structure=[])
    assert t.is_default is False
    assert t.is_system is False


def test_section_defaults():
    from app.models import Section, Project, User
    db = _session()
    u = User(email="a@b.com", password_hash="x", name="A")
    db.add(u); db.flush()
    p = Project(user_id=u.id, title="P")
    db.add(p); db.flush()
    s = Section(project_id=p.id, template_section_id="ts1", order=1, key="name", title="发明名称")
    db.add(s); db.flush()
    assert s.status == "empty"
    assert s.content is None
```

- [ ] **Step 8: 生成并应用迁移**

```bash
cd apps/api && uv run alembic revision --autogenerate -m "add templates parse_jobs sections"
cd apps/api && uv run alembic upgrade head
```
检查生成的迁移含 templates/parse_jobs/sections 三张表的 create_table。

- [ ] **Step 9: 运行测试 + Commit**

```bash
cd apps/api && uv run pytest tests/test_models.py -v
git add apps/api/app/models/ apps/api/alembic/versions/ apps/api/tests/test_models.py
git commit -m "feat: Template/ParseJob/Section 数据模型与迁移"
```

---

## 任务 1：系统默认模板种子

**Files:**
- Create: `apps/api/app/services/seed_service.py`
- Create: `apps/api/scripts/seed_default_template.py`

- [ ] **Step 1: 实现种子服务**

Create `apps/api/app/services/seed_service.py`:
```python
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
```

- [ ] **Step 2: 命令行种子脚本**

Create `apps/api/scripts/seed_default_template.py`:
```python
"""初始化系统默认模板。"""
from app.core.database import SessionLocal
from app.services.seed_service import ensure_default_template


def main():
    db = SessionLocal()
    try:
        tpl = ensure_default_template(db)
        print(f"默认模板就绪：{tpl.name} (id={tpl.id})")
    finally:
        db.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: 执行种子 + Commit**

```bash
cd apps/api && uv run python -m scripts.seed_default_template
git add apps/api/app/services/seed_service.py apps/api/scripts/seed_default_template.py
git commit -m "feat: 系统默认模板种子（8 章节标准交底书）"
```

---

## 任务 2：Word 解析器——章节结构提取

**Files:**
- Create: `apps/api/app/parsing/__init__.py`
- Create: `apps/api/app/parsing/structure_extractor.py`
- Test: `apps/api/tests/test_parsing.py`

- [ ] **Step 1: 安装 python-docx**

```bash
cd apps/api && uv add python-docx
```

- [ ] **Step 2: 写结构提取的失败测试**

Create `apps/api/tests/test_parsing.py`:
```python
import pytest
from app.parsing.structure_extractor import extract_structure


def _make_docx_with_headings():
    """构造一个含 Heading 样式段落的 docx（内存）。"""
    from docx import Document
    doc = Document()
    doc.add_heading("发明名称", level=1)
    doc.add_paragraph("一些正文内容")
    doc.add_heading("技术领域", level=1)
    doc.add_heading("现有技术", level=2)
    doc.add_paragraph("更多正文")
    return doc


def test_extract_structure_from_headings():
    doc = _make_docx_with_headings()
    sections = extract_structure(doc)
    assert len(sections) == 3
    assert sections[0]["title"] == "发明名称"
    assert sections[0]["level"] == 1
    assert sections[2]["title"] == "现有技术"
    assert sections[2]["level"] == 2


def test_extract_structure_assigns_keys_by_title():
    """标题匹配已知章节时自动分配 key。"""
    doc = _make_docx_with_headings()
    sections = extract_structure(doc)
    # "发明名称" → key="name"
    assert sections[0]["key"] == "name"
    # "技术领域" → key="field"
    assert sections[1]["key"] == "field"


def test_extract_structure_unknown_title_gets_custom_key():
    from docx import Document
    doc = Document()
    doc.add_heading("某自定义章节", level=1)
    sections = extract_structure(doc)
    assert sections[0]["key"] == "custom"


def test_extract_structure_no_headings_falls_back_to_empty():
    """无 Heading 时返回空列表（后续由编号兜底处理）。"""
    from docx import Document
    doc = Document()
    doc.add_paragraph("只有正文，没有标题")
    sections = extract_structure(doc)
    assert sections == []
```

- [ ] **Step 3: 运行测试确认失败**

```bash
cd apps/api && uv run pytest tests/test_parsing.py -v
```

- [ ] **Step 4: 实现 structure_extractor**

Create `apps/api/app/parsing/__init__.py`（空）。

Create `apps/api/app/parsing/structure_extractor.py`:
```python
"""从 Word 文档提取章节结构（基于 Heading 样式名）。"""

# 标题关键词 → 章节 key 映射（用于自动识别章节类型）
TITLE_KEY_MAP = {
    "发明名称": "name",
    "技术领域": "field",
    "背景技术": "background",
    "发明目的": "problem",
    "技术问题": "problem",
    "技术方案": "solution",
    "有益效果": "effect",
    "附图说明": "drawings",
    "具体实施方式": "embodiment",
}


def _guess_key(title: str) -> str:
    """根据标题文本猜测章节 key。"""
    for keyword, key in TITLE_KEY_MAP.items():
        if keyword in title:
            return key
    return "custom"


def extract_structure(doc) -> list[dict]:
    """从 python-docx Document 提取章节结构。

    遍历段落，按 Heading 样式名（Heading 1/2/3...）识别章节。
    返回 [{id, order, key, title, level}, ...]
    """
    sections = []
    order = 0
    for para in doc.paragraphs:
        style_name = para.style.name if para.style else ""
        # 识别 Heading 样式（"Heading 1" / "heading 1" / "标题 1"）
        level = _parse_heading_level(style_name)
        if level is None:
            continue
        title = para.text.strip()
        if not title:
            continue
        order += 1
        key = _guess_key(title)
        sections.append({
            "id": f"sec-{order}",
            "order": order,
            "key": key,
            "title": title,
            "level": level,
        })
    return sections


def _parse_heading_level(style_name: str) -> int | None:
    """从样式名解析 Heading 级别。返回 None 表示不是 Heading。"""
    name = style_name.lower().strip()
    # 英文 "heading 1" / 中文 "标题 1"
    for prefix in ("heading ", "标题 "):
        if name.startswith(prefix):
            try:
                return int(name[len(prefix):])
            except ValueError:
                return None
    return None
```

- [ ] **Step 5: 运行测试确认通过**

```bash
cd apps/api && uv run pytest tests/test_parsing.py -v
```

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/parsing/ apps/api/tests/test_parsing.py apps/api/pyproject.toml apps/api/uv.lock
git commit -m "feat: Word 章节结构提取（Heading 样式 + 标题关键词识别 key）"
```

---

## 任务 3：Word 解析器——样式提取 + 编号解析

**Files:**
- Create: `apps/api/app/parsing/style_extractor.py`
- Create: `apps/api/app/parsing/numbering_resolver.py`
- Modify: `apps/api/tests/test_parsing.py`（追加）

- [ ] **Step 1: 写样式提取测试**

追加到 `apps/api/tests/test_parsing.py`:
```python
def test_extract_styles_basic():
    from app.parsing.style_extractor import extract_styles
    doc = _make_docx_with_headings()
    styles = extract_styles(doc)
    assert "heading_1" in styles or "heading1" in styles or len(styles) > 0
    # 每个样式条目应有 font/size 等字段（可能为 None）
    for key, val in styles.items():
        assert isinstance(val, dict)
```

- [ ] **Step 2: 实现 style_extractor**

Create `apps/api/app/parsing/style_extractor.py`:
```python
"""提取 Word 文档的样式信息（字体/字号/加粗，含继承解析）。"""

from docx.document import Document


def extract_styles(doc) -> dict:
    """提取各级标题和正文的样式。

    返回 {style_key: {font, size, bold, ...}, ...}
    style_key 如 "heading_1" / "normal"
    """
    result = {}
    for style in doc.styles:
        # 只关心段落样式
        if style.type is not None and style.name is None:
            continue
        name = (style.name or "").lower().replace(" ", "_")
        if not name:
            continue
        font = style.font
        result[name] = {
            "font_name": _resolve_font_name(font),
            "font_size": font.size.pt if font.size else None,
            "bold": font.bold,
            "italic": font.italic,
        }
    return result


def _resolve_font_name(font) -> str | None:
    """解析字体名，含东亚字体（中文）。"""
    if font.name:
        return font.name
    # 尝试读 eastAsia 字体（中文文档常见）
    try:
        rpr = font.element
        if rpr is not None:
            from lxml import etree
            ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
            rfonts = rpr.find(".//w:rFonts", ns)
            if rfonts is not None:
                return rfonts.get(f"{{{ns['w']}}}eastAsia") or rfonts.get(f"{{{ns['w']}}}ascii")
    except Exception:
        pass
    return None
```

- [ ] **Step 3: 写编号解析测试**

追加到 `apps/api/tests/test_parsing.py`:
```python
def test_resolve_numbering_from_text_fallback():
    """正则兜底：段落文本以 1.1 开头时提取编号。"""
    from app.parsing.numbering_resolver import extract_numbering_from_text
    assert extract_numbering_from_text("1.1 这是章节") == "1.1"
    assert extract_numbering_from_text("1.1.2 内容") == "1.1.2"
    assert extract_numbering_from_text("2、标题") == "2"
    assert extract_numbering_from_text("无编号的正文") is None


def test_resolve_numbering_format():
    """从 numbering.xml 解析编号格式模板。"""
    from app.parsing.numbering_resolver import NumberingResolver
    resolver = NumberingResolver(None)  # 无 numbering part 时优雅降级
    # 无 numbering.xml 时应返回空结果，不报错
    assert resolver.resolve_for_paragraph(None) is None
```

- [ ] **Step 4: 实现 numbering_resolver**

Create `apps/api/app/parsing/numbering_resolver.py`:
```python
"""解析 Word 自动编号。

Word 的自动编号（1. / 1.1 / 1.1.1）是渲染时计算的，document.xml 只存
numId 引用。本模块尽力解析 numbering.xml，并提供正则兜底（手敲编号）。

详见设计文档 9.6 与 GOTCHAS（python-docx 编号限制）。
"""

import re

# 正则：匹配 "1." / "1.1" / "1.1.1" / "1、" 等开头的编号
_NUMBER_RE = re.compile(r"^(\d+(?:\.\d+)*)[\.、]")

# OOXML 命名空间
_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def extract_numbering_from_text(text: str) -> str | None:
    """正则兜底：从段落文本提取手敲的编号。"""
    if not text:
        return None
    m = _NUMBER_RE.match(text.strip())
    return m.group(1) if m else None


class NumberingResolver:
    """解析 numbering.xml 的自动编号。

    对于 MVP，优先保证不报错（无 numbering.xml 或解析失败时优雅降级）。
    完整的计数器逻辑较复杂，此处实现基础版 + 正则兜底。
    """

    def __init__(self, numbering_part_element):
        """numbering_part_element: doc.part.numbering_part.element（lxml），可为 None。"""
        self._element = numbering_part_element
        self._abstract_nums = {}  # abstractNumId -> {ilvl: {lvlText, numFmt, start}}
        self._num_to_abstract = {}  # numId -> abstractNumId
        self._counters = {}  # (numId, ilvl) -> 当前计数值
        if self._element is not None:
            self._parse_numbering_xml()

    def _parse_numbering_xml(self):
        """解析 numbering.xml 的 abstractNum 定义。"""
        from lxml import etree
        # 解析 num -> abstractNum 映射
        for num in self._element.findall(f"{{{_W_NS}}}num"):
            num_id = num.get(f"{{{_W_NS}}}numId")
            abs_ref = num.find(f"{{{_W_NS}}}abstractNumId")
            if abs_ref is not None:
                self._num_to_abstract[num_id] = abs_ref.get(f"{{{_W_NS}}}val")
        # 解析 abstractNum 的各级定义
        for abs_num in self._element.findall(f"{{{_W_NS}}}abstractNum"):
            abs_id = abs_num.get(f"{{{_W_NS}}}abstractNumId")
            levels = {}
            for lvl in abs_num.findall(f"{{{_W_NS}}}lvl"):
                ilvl = lvl.get(f"{{{_W_NS}}}ilvl")
                lvl_text = lvl.find(f"{{{_W_NS}}}lvlText")
                num_fmt = lvl.find(f"{{{_W_NS}}}numFmt")
                start = lvl.find(f"{{{_W_NS}}}start")
                levels[ilvl] = {
                    "lvlText": lvl_text.get(f"{{{_W_NS}}}val") if lvl_text is not None else None,
                    "numFmt": num_fmt.get(f"{{{_W_NS}}}val") if num_fmt is not None else None,
                    "start": int(start.get(f"{{{_W_NS}}}val")) if start is not None else 1,
                }
            self._abstract_nums[abs_id] = levels

    def resolve_for_paragraph(self, paragraph) -> str | None:
        """尝试解析某段落的自动编号。无编号信息时返回 None（降级到正则）。"""
        if paragraph is None:
            return None
        try:
            pPr = paragraph._element.find(f"{{{_W_NS}}}pPr")
            if pPr is None:
                return None
            numPr = pPr.find(f"{{{_W_NS}}}numPr")
            if numPr is None:
                return None
            num_id_el = numPr.find(f"{{{_W_NS}}}numId")
            ilvl_el = numPr.find(f"{{{_W_NS}}}ilvl")
            if num_id_el is None:
                return None
            num_id = num_id_el.get(f"{{{_W_NS}}}val")
            ilvl = ilvl_el.get(f"{{{_W_NS}}}val") if ilvl_el is not None else "0"
            abs_id = self._num_to_abstract.get(num_id)
            if abs_id is None or abs_id not in self._abstract_nums:
                return None
            levels = self._abstract_nums[abs_id]
            if ilvl not in levels:
                return None
            # 自增计数器（简化：不处理 startOverride）
            counter_key = (num_id, ilvl)
            self._counters[counter_key] = self._counters.get(counter_key, levels[ilvl]["start"] - 1) + 1
            count = self._counters[counter_key]
            # 用 lvlText 模板替换 %N（简化版，只替换当前层）
            lvl_text = levels[ilvl]["lvlText"] or ""
            return lvl_text.replace(f"%{int(ilvl) + 1}", str(count))
        except Exception:
            # 任何解析异常都降级（不阻断模板创建）
            return None
```

- [ ] **Step 5: 运行测试确认通过**

```bash
cd apps/api && uv run pytest tests/test_parsing.py -v
```

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/parsing/style_extractor.py apps/api/app/parsing/numbering_resolver.py apps/api/tests/test_parsing.py
git commit -m "feat: Word 样式提取与编号解析（NumberingResolver + 正则兜底）"
```

---

## 任务 4：解析编排 + 异步任务

**Files:**
- Create: `apps/api/app/parsing/docx_parser.py`
- Create: `apps/api/app/services/parse_service.py`
- Test: `apps/api/tests/test_parsing.py`（追加集成测试）

- [ ] **Step 1: 实现 docx_parser（编排三个提取器）**

Create `apps/api/app/parsing/docx_parser.py`:
```python
"""Word 文档解析编排：调用结构/样式/编号提取器，组装成 Template 数据。"""

from dataclasses import dataclass

from app.parsing.numbering_resolver import NumberingResolver, extract_numbering_from_text
from app.parsing.structure_extractor import extract_structure
from app.parsing.style_extractor import extract_styles


@dataclass
class ParsedTemplate:
    structure: list[dict]
    styles: dict
    numbering: dict


def parse_docx(doc) -> ParsedTemplate:
    """解析 python-docx Document，返回结构化模板数据。"""
    # 1. 章节结构（Heading 优先）
    structure = extract_structure(doc)

    # 2. 样式
    styles = extract_styles(doc)

    # 3. 编号
    numbering = _extract_numbering(doc, structure)

    return ParsedTemplate(structure=structure, styles=styles, numbering=numbering)


def _extract_numbering(doc, structure: list[dict]) -> dict:
    """提取编号规则：尝试 numbering.xml，正则兜底。"""
    # 尝试拿 numbering part
    resolver = None
    try:
        numbering_part = doc.part.numbering_part
        resolver = NumberingResolver(numbering_part.element) if numbering_part else NumberingResolver(None)
    except Exception:
        resolver = NumberingResolver(None)

    # 对每个章节，尝试解析编号
    section_numbers = {}
    paragraphs = doc.paragraphs
    para_idx = 0
    for section in structure:
        # 找到该章节标题对应的段落位置（简化：按顺序匹配）
        # 正则兜底
        for p in paragraphs[para_idx:]:
            para_idx += 1
            if p.text.strip() == section["title"]:
                num = resolver.resolve_for_paragraph(p)
                if num is None:
                    num = extract_numbering_from_text(p.text)
                if num:
                    section_numbers[section["id"]] = num
                break

    return {"section_numbers": section_numbers, "resolver_available": resolver._element is not None}
```

- [ ] **Step 2: 实现 parse_service（异步解析编排）**

Create `apps/api/app/services/parse_service.py`:
```python
"""模板解析服务：上传 → 异步解析 → 存 Template。"""

import os
import uuid

from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.models import ParseJob, Template


def create_parse_job(db: Session, *, user_id, filename: str, file_bytes: bytes, upload_dir: str) -> ParseJob:
    """保存上传文件，创建 ParseJob。"""
    os.makedirs(upload_dir, exist_ok=True)
    stored_name = f"{uuid.uuid4()}.docx"
    file_path = os.path.join(upload_dir, stored_name)
    with open(file_path, "wb") as f:
        f.write(file_bytes)

    job = ParseJob(
        user_id=user_id,
        source_path=file_path,
        status="pending",
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def run_parse_job(db: Session, job_id: str, upload_dir: str) -> ParseJob:
    """执行解析任务（同步实现，生产可用 BackgroundTasks 调用）。"""
    job = db.get(ParseJob, job_id)
    if job is None:
        raise NotFoundError("解析任务不存在")
    if job.status == "completed":
        return job

    job.status = "processing"
    db.commit()

    try:
        from docx import Document
        from app.parsing.docx_parser import parse_docx

        doc = Document(job.source_path)
        parsed = parse_docx(doc)

        # 若无章节结构（无 Heading），降级为单章节
        structure = parsed.structure or [
            {"id": "sec-1", "order": 1, "key": "custom", "title": "正文内容", "level": 1}
        ]

        template = Template(
            user_id=job.user_id,
            name=_derive_template_name(job.source_path),
            source_filename=os.path.basename(job.source_path),
            structure=structure,
            styles=parsed.styles,
            numbering=parsed.numbering,
        )
        db.add(template)
        job.template_id = template.id
        job.status = "completed"
        from datetime import datetime, timezone
        job.completed_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(job)
        return job
    except Exception as e:
        job.status = "failed"
        job.error_message = str(e)[:500]
        db.commit()
        db.refresh(job)
        return job


def _derive_template_name(source_path: str) -> str:
    """从文件名推导模板名。"""
    import os
    base = os.path.basename(source_path)
    name = os.path.splitext(base)[0]
    # 去掉 uuid 前缀（如果有）
    return name[:100] if name else "上传的模板"
```

- [ ] **Step 3: 写集成测试**

追加到 `apps/api/tests/test_parsing.py`:
```python
def test_parse_docx_integration():
    """端到端：构造 docx → 解析 → 得到 structure/styles/numbering。"""
    from io import BytesIO
    from docx import Document
    from app.parsing.docx_parser import parse_docx

    doc = _make_docx_with_headings()
    parsed = parse_docx(doc)
    assert len(parsed.structure) == 3
    assert parsed.structure[0]["key"] == "name"
    assert isinstance(parsed.styles, dict)
    assert isinstance(parsed.numbering, dict)
```

- [ ] **Step 4: 运行测试 + Commit**

```bash
cd apps/api && uv run pytest tests/test_parsing.py -v
git add apps/api/app/parsing/docx_parser.py apps/api/app/services/parse_service.py apps/api/tests/test_parsing.py
git commit -m "feat: Word 解析编排与异步解析服务"
```

---

## 任务 5：模板与章节 API

**Files:**
- Create: `apps/api/app/schemas/template.py`
- Create: `apps/api/app/schemas/section.py`
- Create: `apps/api/app/services/template_service.py`
- Create: `apps/api/app/services/section_service.py`
- Create: `apps/api/app/api/templates.py`
- Create: `apps/api/app/api/sections.py`
- Modify: `apps/api/app/api/router.py`
- Modify: `apps/api/app/services/project_service.py`（创建项目时生成 sections）
- Test: `apps/api/tests/test_templates.py`, `apps/api/tests/test_sections.py`

- [ ] **Step 1: 实现 schemas**

Create `apps/api/app/schemas/template.py`:
```python
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class TemplateSection(BaseModel):
    id: str
    order: int
    key: str
    title: str
    level: int


class TemplateOut(BaseModel):
    id: str
    name: str
    source_filename: str | None
    structure: list[dict]
    styles: dict | None
    numbering: dict | None
    is_default: bool
    is_system: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class TemplateSummary(BaseModel):
    """列表用的精简版（不含 structure 细节）。"""
    id: str
    name: str
    is_default: bool
    is_system: bool
    section_count: int

    model_config = {"from_attributes": True}
```

Create `apps/api/app/schemas/section.py`:
```python
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class SectionOut(BaseModel):
    id: str
    project_id: str
    order: int
    key: str
    title: str
    content: dict | None
    summary: str | None
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SectionUpdate(BaseModel):
    content: dict | None = None
    status: str | None = None  # empty/drafting/confirmed
```

- [ ] **Step 2: 实现 template_service**

Create `apps/api/app/services/template_service.py`:
```python
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError
from app.models import Template


def list_templates(db: Session, *, user_id) -> list[Template]:
    """列出用户的模板 + 系统默认模板。"""
    return list(db.scalars(
        select(Template).where(
            (Template.user_id == user_id) | (Template.is_system.is_(True))
        ).order_by(Template.is_system.desc(), Template.created_at.desc())
    ))


def get_template(db: Session, *, user_id, template_id: str) -> Template:
    from uuid import UUID
    try:
        tid = UUID(template_id)
    except ValueError:
        raise NotFoundError("模板不存在")
    tpl = db.scalar(select(Template).where(Template.id == tid))
    if tpl is None:
        raise NotFoundError("模板不存在")
    # 系统模板人人可读；用户模板仅本人
    if not tpl.is_system and tpl.user_id != user_id:
        raise NotFoundError("模板不存在")
    return tpl


def delete_template(db: Session, *, user_id, template_id: str) -> None:
    tpl = get_template(db, user_id=user_id, template_id=template_id)
    if tpl.is_system:
        raise ConflictError("系统模板不可删除")
    db.delete(tpl)
    db.commit()


def set_default(db: Session, *, user_id, template_id: str) -> Template:
    tpl = get_template(db, user_id=user_id, template_id=template_id)
    # 取消该用户其他默认
    user_templates = db.scalars(
        select(Template).where(
            (Template.user_id == user_id) & (Template.is_default.is_(True))
        )
    )
    for t in user_templates:
        t.is_default = False
    tpl.is_default = True
    db.commit()
    db.refresh(tpl)
    return tpl
```

- [ ] **Step 3: 实现 section_service**

Create `apps/api/app/services/section_service.py`:
```python
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.models import Project, Section


def list_sections(db: Session, *, user_id, project_id: str) -> list[Section]:
    """列出项目的章节。先校验项目归属。"""
    from app.services.project_service import get_project
    from app.models import User
    # 复用项目归属校验
    # get_project 需要 user 对象，这里简化：直接查
    from uuid import UUID
    try:
        pid = UUID(project_id)
    except ValueError:
        raise NotFoundError("项目不存在")
    project = db.scalar(select(Project).where(Project.id == pid))
    if project is None or project.user_id != user_id:
        raise NotFoundError("项目不存在")
    return list(db.scalars(
        select(Section).where(Section.project_id == pid).order_by(Section.order)
    ))


def get_section(db: Session, *, user_id, section_id: str) -> Section:
    from uuid import UUID
    try:
        sid = UUID(section_id)
    except ValueError:
        raise NotFoundError("章节不存在")
    section = db.scalar(select(Section).where(Section.id == sid))
    if section is None:
        raise NotFoundError("章节不存在")
    # 通过 project 校验归属
    project = db.scalar(select(Project).where(Project.id == section.project_id))
    if project is None or project.user_id != user_id:
        raise NotFoundError("章节不存在")
    return section


def update_section(db: Session, *, user_id, section_id: str, content=None, status=None) -> Section:
    section = get_section(db, user_id=user_id, section_id=section_id)
    if content is not None:
        section.content = content
    if status is not None:
        if status not in ("empty", "drafting", "confirmed"):
            from app.core.exceptions import ValidationError
            raise ValidationError("无效的章节状态")
        section.status = status
    db.commit()
    db.refresh(section)
    return section
```

- [ ] **Step 4: 修改 project_service——创建项目时生成 sections**

Modify `apps/api/app/services/project_service.py` 的 `create_project`，在创建项目后根据模板生成 sections:

```python
def create_project(
    db: Session, *, user: User, title: str,
    template_id: str | None = None,
    metadata: dict | None = None,
) -> Project:
    import uuid
    # 解析模板
    tpl = None
    if template_id:
        tpl = db.get(Template, uuid.UUID(template_id))
    if tpl is None:
        # 默认用系统默认模板
        tpl = db.scalar(select(Template).where(Template.is_default.is_(True)))
    if tpl is None:
        tpl = db.scalar(select(Template).where(Template.is_system.is_(True)))

    project = Project(
        user_id=user.id,
        template_id=tpl.id if tpl else None,
        title=title,
        metadata_=metadata,
    )
    db.add(project)
    db.flush()

    # 按模板结构快照生成 sections（创建时快照，详见设计 9.7）
    if tpl:
        for ts in tpl.structure:
            section = Section(
                project_id=project.id,
                template_section_id=ts.get("id", ""),
                order=ts.get("order", 0),
                key=ts.get("key", "custom"),
                title=ts.get("title", ""),
            )
            db.add(section)

    db.commit()
    db.refresh(project)
    return project
```

记得在文件顶部加 `from app.models import Section, Template`。

- [ ] **Step 5: 实现 templates API 路由**

Create `apps/api/app/api/templates.py`:
```python
from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.deps import get_current_user
from app.models import User
from app.schemas.template import TemplateOut, TemplateSummary
from app.services import parse_service, template_service

router = APIRouter(prefix="/templates", tags=["templates"])
_settings = get_settings()


@router.get("", response_model=list[TemplateSummary])
def list_all(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    templates = template_service.list_templates(db, user_id=current_user.id)
    return [
        TemplateSummary(
            id=str(t.id), name=t.name, is_default=t.is_default,
            is_system=t.is_system, section_count=len(t.structure),
        )
        for t in templates
    ]


@router.post("", response_model=dict, status_code=202)
async def upload(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """上传 Word 文件创建模板。返回 parse_job_id，前端轮询状态。"""
    if not file.filename or not file.filename.lower().endswith(".docx"):
        from app.core.exceptions import ValidationError
        raise ValidationError("仅支持 .docx 文件")
    content = await file.read()
    upload_dir = _settings.database_url and "uploads"  # 简化：用项目根 uploads/
    job = parse_service.create_parse_job(
        db, user_id=current_user.id, filename=file.filename,
        file_bytes=content, upload_dir="uploads",
    )
    # 同步执行解析（MVP 简化，后续可改 BackgroundTasks）
    parse_service.run_parse_job(db, str(job.id), "uploads")
    return {"parse_job_id": str(job.id), "status": "completed"}


@router.get("/{template_id}", response_model=TemplateOut)
def get_one(template_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    t = template_service.get_template(db, user_id=current_user.id, template_id=template_id)
    return TemplateOut(
        id=str(t.id), name=t.name, source_filename=t.source_filename,
        structure=t.structure, styles=t.styles, numbering=t.numbering,
        is_default=t.is_default, is_system=t.is_system, created_at=t.created_at,
    )


@router.delete("/{template_id}", status_code=204)
def delete(template_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    template_service.delete_template(db, user_id=current_user.id, template_id=template_id)
    return None


@router.post("/{template_id}/default", response_model=TemplateSummary)
def set_default(template_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    t = template_service.set_default(db, user_id=current_user.id, template_id=template_id)
    return TemplateSummary(
        id=str(t.id), name=t.name, is_default=t.is_default,
        is_system=t.is_system, section_count=len(t.structure),
    )
```

- [ ] **Step 6: 实现 sections API 路由**

Create `apps/api/app/api/sections.py`:
```python
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.deps import get_current_user
from app.models import User
from app.schemas.section import SectionOut, SectionUpdate
from app.services import section_service

router = APIRouter(tags=["sections"])


@router.get("/projects/{project_id}/sections", response_model=list[SectionOut])
def list_sections(project_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    sections = section_service.list_sections(db, user_id=current_user.id, project_id=project_id)
    return [SectionOut(
        id=str(s.id), project_id=str(s.project_id), order=s.order, key=s.key,
        title=s.title, content=s.content, summary=s.summary, status=s.status,
        created_at=s.created_at, updated_at=s.updated_at,
    ) for s in sections]


@router.get("/sections/{section_id}", response_model=SectionOut)
def get_section(section_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    s = section_service.get_section(db, user_id=current_user.id, section_id=section_id)
    return SectionOut(
        id=str(s.id), project_id=str(s.project_id), order=s.order, key=s.key,
        title=s.title, content=s.content, summary=s.summary, status=s.status,
        created_at=s.created_at, updated_at=s.updated_at,
    )


@router.patch("/sections/{section_id}", response_model=SectionOut)
def update_section(section_id: str, payload: SectionUpdate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    s = section_service.update_section(
        db, user_id=current_user.id, section_id=section_id,
        content=payload.content, status=payload.status,
    )
    return SectionOut(
        id=str(s.id), project_id=str(s.project_id), order=s.order, key=s.key,
        title=s.title, content=s.content, summary=s.summary, status=s.status,
        created_at=s.created_at, updated_at=s.updated_at,
    )
```

- [ ] **Step 7: 注册路由**

Modify `apps/api/app/api/router.py`:
```python
from fastapi import APIRouter

from app.api import auth, health, projects, sections, templates

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(projects.router)
api_router.include_router(templates.router)
api_router.include_router(sections.router)
api_router.include_router(health.router)
```

- [ ] **Step 8: 写 API 测试**

Create `apps/api/tests/test_templates.py`:
```python
def test_list_templates_includes_system(client, registered_user, db_session):
    from app.services.seed_service import ensure_default_template
    ensure_default_template(db_session)

    client.post("/api/v1/auth/login", json={
        "email": registered_user["email"], "password": registered_user["password"],
    })
    res = client.get("/api/v1/templates")
    assert res.status_code == 200
    data = res.json()
    assert len(data) >= 1
    assert any(t["is_system"] for t in data)


def test_get_template_detail(client, registered_user, db_session):
    from app.services.seed_service import ensure_default_template
    tpl = ensure_default_template(db_session)

    client.post("/api/v1/auth/login", json={
        "email": registered_user["email"], "password": registered_user["password"],
    })
    res = client.get(f"/api/v1/templates/{tpl.id}")
    assert res.status_code == 200
    assert len(res.json()["structure"]) == 8
```

Create `apps/api/tests/test_sections.py`:
```python
def test_create_project_generates_sections(client, registered_user, db_session):
    from app.services.seed_service import ensure_default_template
    ensure_default_template(db_session)

    client.post("/api/v1/auth/login", json={
        "email": registered_user["email"], "password": registered_user["password"],
    })
    # 创建项目
    res = client.post("/api/v1/projects", json={"title": "测试发明"})
    project_id = res.json()["id"]

    # 应自动生成 8 个章节
    res = client.get(f"/api/v1/projects/{project_id}/sections")
    assert res.status_code == 200
    sections = res.json()
    assert len(sections) == 8
    assert sections[0]["key"] == "name"
    assert sections[0]["status"] == "empty"


def test_update_section_content(client, registered_user, db_session):
    from app.services.seed_service import ensure_default_template
    ensure_default_template(db_session)

    client.post("/api/v1/auth/login", json={
        "email": registered_user["email"], "password": registered_user["password"],
    })
    res = client.post("/api/v1/projects", json={"title": "测试发明"})
    project_id = res.json()["id"]
    sections = client.get(f"/api/v1/projects/{project_id}/sections").json()
    section_id = sections[0]["id"]

    # 更新章节内容
    res = client.patch(f"/api/v1/sections/{section_id}", json={
        "content": {"type": "doc", "content": [{"type": "paragraph"}]},
        "status": "drafting",
    })
    assert res.status_code == 200
    assert res.json()["status"] == "drafting"
    assert res.json()["content"] is not None
```

- [ ] **Step 9: 运行测试 + Commit**

```bash
cd apps/api && uv run pytest tests/test_templates.py tests/test_sections.py -v
git add apps/api/app/schemas/ apps/api/app/services/ apps/api/app/api/ apps/api/tests/
git commit -m "feat: 模板与章节 API（含创建项目自动生成章节）"
```

---

## 任务 6：前端——Tiptap 编辑器集成

**Files:**
- Install: `@tiptap/react @tiptap/starter-kit @tiptap/extension-placeholder`
- Create: `apps/web/src/components/editor/tiptap-editor.tsx`
- Create: `apps/web/src/components/editor/toolbar.tsx`

- [ ] **Step 1: 安装 Tiptap**

```bash
cd apps/web && pnpm add @tiptap/react @tiptap/starter-kit @tiptap/extension-placeholder @tiptap/pm
```

- [ ] **Step 2: 实现编辑器组件**

Create `apps/web/src/components/editor/tiptap-editor.tsx`:
```tsx
'use client'

import { useEditor, EditorContent } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import Placeholder from '@tiptap/extension-placeholder'

import { Toolbar } from './toolbar'

interface TiptapEditorProps {
  content?: object | null
  onChange?: (json: object) => void
  editable?: boolean
}

export function TiptapEditor({ content, onChange, editable = true }: TiptapEditorProps) {
  const editor = useEditor({
    extensions: [
      StarterKit,
      Placeholder.configure({ placeholder: '在此撰写内容...' }),
    ],
    content: content || undefined,
    editable,
    onUpdate: ({ editor }) => {
      onChange?.(editor.getJSON())
    },
  })

  if (!editor) return null

  return (
    <div className="border rounded-lg">
      <Toolbar editor={editor} />
      <EditorContent editor={editor} className="prose prose-sm max-w-none p-4 min-h-[300px] focus:outline-none" />
    </div>
  )
}
```

- [ ] **Step 3: 实现工具栏**

Create `apps/web/src/components/editor/toolbar.tsx`:
```tsx
'use client'

import type { Editor } from '@tiptap/react'

import { Button } from '@/components/ui/button'

interface ToolbarProps {
  editor: Editor
}

export function Toolbar({ editor }: ToolbarProps) {
  if (!editor) return null

  const tools = [
    { label: 'B', action: () => editor.chain().focus().toggleBold().run(), active: editor.isActive('bold') },
    { label: 'I', action: () => editor.chain().focus().toggleItalic().run(), active: editor.isActive('italic') },
    { label: 'H2', action: () => editor.chain().focus().toggleHeading({ level: 2 }).run(), active: editor.isActive('heading', { level: 2 }) },
    { label: 'H3', action: () => editor.chain().focus().toggleHeading({ level: 3 }).run(), active: editor.isActive('heading', { level: 3 }) },
    { label: '• 列表', action: () => editor.chain().focus().toggleBulletList().run(), active: editor.isActive('bulletList') },
    { label: '1. 列表', action: () => editor.chain().focus().toggleOrderedList().run(), active: editor.isActive('orderedList') },
  ]

  return (
    <div className="flex flex-wrap gap-1 border-b p-2">
      {tools.map((t) => (
        <Button
          key={t.label}
          variant={t.active ? 'default' : 'ghost'}
          size="sm"
          onClick={t.action}
          type="button"
        >
          {t.label}
        </Button>
      ))}
    </div>
  )
}
```

- [ ] **Step 4: Commit**

```bash
git add apps/web/src/components/editor/ apps/web/package.json apps/web/pnpm-lock.yaml
git commit -m "feat: Tiptap 富文本编辑器集成（工具栏 + JSON 输出）"
```

---

## 任务 7：前端——项目详情页（大纲 + 编辑器）

**Files:**
- Modify: `apps/web/src/lib/queries.ts`（加 sections/templates hooks）
- Modify: `apps/web/src/types/api.ts`（加 Template/Section 类型）
- Create: `apps/web/src/components/section-outline.tsx`
- Create: `apps/web/src/app/(app)/projects/[id]/page.tsx`

- [ ] **Step 1: 扩展类型定义**

追加到 `apps/web/src/types/api.ts`:
```typescript
export interface TemplateSummary {
  id: string
  name: string
  is_default: boolean
  is_system: boolean
  section_count: number
}

export interface Template extends TemplateSummary {
  source_filename: string | null
  structure: TemplateSection[]
  styles: Record<string, unknown> | null
  numbering: Record<string, unknown> | null
  created_at: string
}

export interface TemplateSection {
  id: string
  order: number
  key: string
  title: string
  level: number
}

export interface Section {
  id: string
  project_id: string
  order: number
  key: string
  title: string
  content: Record<string, unknown> | null
  summary: string | null
  status: 'empty' | 'drafting' | 'confirmed'
  created_at: string
  updated_at: string
}
```

- [ ] **Step 2: 扩展 Query hooks**

追加到 `apps/web/src/lib/queries.ts`:
```typescript
import type { Section, TemplateSummary } from '@/types/api'

// 加到 queryKeys
// templates: ['templates'] as const,
// sections: (id: string) => ['sections', id] as const,

export function useTemplates() {
  return useQuery<TemplateSummary[]>({
    queryKey: ['templates'],
    queryFn: () => api.fetch<TemplateSummary[]>('/templates'),
  })
}

export function useSections(projectId: string) {
  return useQuery<Section[]>({
    queryKey: ['sections', projectId],
    queryFn: () => api.fetch<Section[]>(`/projects/${projectId}/sections`),
    enabled: !!projectId,
  })
}

export function useUpdateSection() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, content, status }: { id: string; content?: object; status?: string }) =>
      api.request<Section>(`/sections/${id}`, { method: 'PATCH', body: JSON.stringify({ content, status }) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['sections'] }),
  })
}
```

> 注：api.ts 里需要补一个通用的 `fetch`/`request` 方法，或直接用现有命名。根据实际 api.ts 结构调整。

- [ ] **Step 3: 实现章节大纲组件**

Create `apps/web/src/components/section-outline.tsx`:
```tsx
'use client'

import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import type { Section } from '@/types/api'

const STATUS_DOT: Record<string, string> = {
  empty: 'bg-muted',
  drafting: 'bg-blue-500',
  confirmed: 'bg-green-500',
}

interface SectionOutlineProps {
  sections: Section[]
  currentId: string | null
  onSelect: (id: string) => void
}

export function SectionOutline({ sections, currentId, onSelect }: SectionOutlineProps) {
  return (
    <nav className="space-y-1">
      {sections.map((s) => (
        <button
          key={s.id}
          onClick={() => onSelect(s.id)}
          className={cn(
            'flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm transition-colors',
            currentId === s.id ? 'bg-accent' : 'hover:bg-accent/50',
          )}
        >
          <span className={cn('h-2 w-2 shrink-0 rounded-full', STATUS_DOT[s.status])} />
          <span className="truncate">{s.title}</span>
        </button>
      ))}
    </nav>
  )
}
```

- [ ] **Step 4: 实现项目详情页**

Create `apps/web/src/app/(app)/projects/[id]/page.tsx`:
```tsx
'use client'

import { useParams } from 'next/navigation'
import { useEffect, useState } from 'react'
import { toast } from 'sonner'

import { SectionOutline } from '@/components/section-outline'
import { TiptapEditor } from '@/components/editor/tiptap-editor'
import { Button } from '@/components/ui/button'
import { api } from '@/lib/api'
import { useSections, useUpdateSection } from '@/lib/queries'
import type { Section } from '@/types/api'

export default function ProjectDetailPage() {
  const params = useParams<{ id: string }>()
  const projectId = params.id
  const { data: sections, isLoading } = useSections(projectId)
  const updateSection = useUpdateSection()
  const [currentId, setCurrentId] = useState<string | null>(null)
  const [current, setCurrent] = useState<Section | null>(null)

  useEffect(() => {
    if (sections && sections.length > 0 && !currentId) {
      setCurrentId(sections[0].id)
    }
  }, [sections, currentId])

  useEffect(() => {
    if (sections && currentId) {
      setCurrent(sections.find((s) => s.id === currentId) || null)
    }
  }, [sections, currentId])

  if (isLoading) return <p className="text-muted-foreground">加载中...</p>
  if (!sections || sections.length === 0) {
    return <p className="text-muted-foreground">该项目暂无章节</p>
  }

  function handleSave(json: object) {
    if (!current) return
    updateSection.mutate(
      { id: current.id, content: json, status: 'drafting' },
      { onSuccess: () => toast.success('已保存'), onError: () => toast.error('保存失败') },
    )
  }

  function handleConfirm() {
    if (!current) return
    updateSection.mutate(
      { id: current.id, status: 'confirmed' },
      { onSuccess: () => toast.success('章节已确认'), onError: () => toast.error('操作失败') },
    )
  }

  return (
    <div className="grid grid-cols-[220px_1fr] gap-6">
      {/* 左侧大纲 */}
      <aside className="space-y-4">
        <h2 className="text-sm font-semibold text-muted-foreground">章节大纲</h2>
        <SectionOutline sections={sections} currentId={currentId} onSelect={setCurrentId} />
      </aside>

      {/* 右侧编辑器 */}
      <div className="space-y-4">
        {current && (
          <>
            <div className="flex items-center justify-between">
              <h1 className="text-lg font-bold">{current.title}</h1>
              <Button onClick={handleConfirm} disabled={updateSection.isPending}>
                确认完成
              </Button>
            </div>
            <TiptapEditor content={current.content} onChange={handleSave} />
          </>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 5: 构建验证 + Commit**

```bash
cd apps/web && pnpm build
git add apps/web/src/
git commit -m "feat: 项目详情页（章节大纲 + Tiptap 编辑器 + 保存/确认）"
```

---

## 任务 8：前端——模板管理页

**Files:**
- Create: `apps/web/src/app/(app)/templates/page.tsx`
- Create: `apps/web/src/components/template-manager.tsx`
- Modify: `apps/web/src/components/navbar.tsx`（加模板管理入口）

- [ ] **Step 1: 实现模板管理组件**

Create `apps/web/src/components/template-manager.tsx`（上传 + 列表 + 设默认）:
```tsx
'use client'

import { useRef, useState } from 'react'
import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { api } from '@/lib/api'
import { useTemplates } from '@/lib/queries'

export function TemplateManager() {
  const { data: templates, isLoading, refetch } = useTemplates()
  const fileRef = useRef<HTMLInputElement>(null)
  const [uploading, setUploading] = useState(false)

  async function handleUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    setUploading(true)
    try {
      const form = new FormData()
      form.append('file', file)
      await fetch(`${process.env.NEXT_PUBLIC_API_URL}/api/v1/templates`, {
        method: 'POST',
        credentials: 'include',
        body: form,
      })
      toast.success('模板上传成功')
      refetch()
    } catch {
      toast.error('上传失败')
    } finally {
      setUploading(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  if (isLoading) return <p className="text-muted-foreground">加载中...</p>

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold">模板管理</h1>
        <div>
          <input ref={fileRef} type="file" accept=".docx" onChange={handleUpload} className="hidden" />
          <Button onClick={() => fileRef.current?.click()} disabled={uploading}>
            {uploading ? '上传中...' : '上传 Word 模板'}
          </Button>
        </div>
      </div>

      <div className="space-y-2">
        {templates?.map((t) => (
          <div key={t.id} className="flex items-center justify-between rounded-lg border p-4">
            <div className="space-y-1">
              <div className="flex items-center gap-2">
                <span className="font-medium">{t.name}</span>
                {t.is_system && <Badge variant="secondary">系统</Badge>}
                {t.is_default && <Badge>默认</Badge>}
              </div>
              <p className="text-xs text-muted-foreground">{t.section_count} 个章节</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
```

- [ ] **Step 2: 模板管理页**

Create `apps/web/src/app/(app)/templates/page.tsx`:
```tsx
import { TemplateManager } from '@/components/template-manager'

export default function TemplatesPage() {
  return <TemplateManager />
}
```

- [ ] **Step 3: navbar 加入口**

在 `apps/web/src/components/navbar.tsx` 的 logo 和用户菜单之间加导航链接:
```tsx
<a href="/dashboard" className="text-sm hover:underline">工作台</a>
<a href="/templates" className="text-sm hover:underline">模板</a>
```

- [ ] **Step 4: 构建验证 + Commit**

```bash
cd apps/web && pnpm build
git add apps/web/src/
git commit -m "feat: 模板管理页（上传 Word + 列表 + 设默认）"
```

---

## 任务 9：端到端验证

- [ ] **Step 1: 初始化种子数据**

```bash
cd apps/api && uv run python -m scripts.seed_default_template
```

- [ ] **Step 2: 启动前后端，手动验证完整流程**

```bash
# 终端1
cd apps/api && uv run uvicorn app.main:app --reload
# 终端2
cd apps/web && pnpm dev
```

浏览器验证：
1. 登录 → 工作台 → 新建项目（应自动用默认模板生成 8 章节）
2. 点项目卡片 → 进入项目详情页 → 看到左侧 8 章节大纲 + 右侧编辑器
3. 在编辑器输入内容 → 自动保存（状态变 drafting）
4. 点「确认完成」→ 章节状态变 confirmed（大纲圆点变绿）
5. 切换到其他章节 → 编辑器内容切换
6. 顶栏点「模板」→ 看到系统默认模板（8 章节）
7. 上传一个 Word 文档 → 解析成功出现在列表

- [ ] **Step 3: 全量测试 + Commit**

```bash
cd apps/api && uv run pytest -v
git commit --allow-empty -m "chore: 计划 3 模板与编辑器端到端验证通过"
```

---

## 完成标准

- [ ] Template/ParseJob/Section 三个模型 + 迁移
- [ ] Word 解析器（结构 + 样式 + 编号，含 NumberingResolver + 正则兜底）
- [ ] 系统默认模板种子（8 章节）
- [ ] 创建项目自动按模板生成 sections
- [ ] 模板 API（列表/上传/详情/删除/设默认）
- [ ] 章节 API（列表/详情/更新内容与状态）
- [ ] Tiptap 编辑器集成（工具栏 + JSON 存储）
- [ ] 项目详情页（大纲 + 编辑器 + 保存/确认）
- [ ] 模板管理页（上传/列表）
- [ ] 端到端验证通过

## 后续计划衔接

| 计划 | 本计划预埋 |
|---|---|
| 4 AI 撰写引擎 | Section.key（匹配 Prompt 策略）、Section.content（Tiptap JSON）、章节状态机 |
| 5 版本/导出 | Section.content、Template.styles（导出套样式） |
| 6 知识库 | Section 归档时分块向量化 |
