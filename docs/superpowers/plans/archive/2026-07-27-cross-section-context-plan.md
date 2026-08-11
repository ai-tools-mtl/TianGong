# 跨章节上下文注入（撰写侧方案 D）— TDD 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复"写完一章进下一章，AI 失忆"的真痛点。根因：agent loop 路线（`astream_chat` / `astream_generate`）改造时绕过了上下文装配（`assemble_messages`），导致 agent 拿到的只有静态角色 prompt + 一条孤立指令——看不到项目标题、已写章节、本章节对话历史。本计划实施 4 项修复：L1（agent 接回上下文装配）、L2（透传 history）、L4（项目元信息注入）、前文直注入（同项目所有非空章节纯文本塞 system prompt，不走 summary）。

**Architecture:** 零新增模型/迁移/依赖。`context_assembler.py` 新增 `build_system_prompt(db, section)` + `get_written_sections_text(db, project_id, exclude_key)` + `_format_metadata(metadata)` 三个函数；`agent.py` 的 `build_agent` 扩展 `section=None` 参数，section 非 None 时调 `build_system_prompt` 装配动态 system prompt；`orchestrator.py` 的 `astream_generate` / `astream_chat` 传 `section=section` 给 `build_agent`，并把 `history` 展开成 messages 透传给 agent。旧路径 `stream_*` + `get_project_summaries` 保留不动（已无调用方，作参考实现）。

**Tech Stack:** Python 3.14 / FastAPI / SQLAlchemy 2.0 / `deepagents` 0.6.12（`system_prompt` 构造时锁定，走"每次重建 agent + 动态拼装"路线）/ LangChain（现有）

**Spec:** `docs/superpowers/specs/2026-07-27-cross-section-context-design.md`
**关联 grilling 结论:** 2026-07-27，8 轮 `/grill-me` 质询，决策链见 spec 附录 A
**当前分支：** `feat/firecrawl-web-ingestion`（含未提交的 firecrawl 改动）。本计划开工前应先切到新分支 `feat/cross-section-context`，或与用户确认分支策略
**预计工期：** 3-4 天（周级）

---

## 前置验证（Task 0，开工前必做）

确认基线测试全绿 + 新分支，避免在污染的工作区上动工。

---

## 文件结构

| 文件 | 责任 | 动作 |
|---|---|---|
| `apps/api/app/ai/context_assembler.py` | 新增 `build_system_prompt` / `get_written_sections_text` / `_format_metadata` | 改（新增函数，不动现有 `assemble_messages` / `get_project_summaries` / `SYSTEM_PROMPT`） |
| `apps/api/app/ai/agent.py` | `build_agent` 扩展 `section` 参数 | 改 |
| `apps/api/app/ai/orchestrator.py` | `astream_generate` / `astream_chat` 传 section + 透传 history | 改 |
| `apps/api/tests/test_context.py` | 新增 `build_system_prompt` / `get_written_sections_text` / `_format_metadata` 测试 | 改（扩展，保留现有 4 个测试） |
| `apps/api/tests/test_agent_factory.py` | 新增 build_agent 传 section 的测试 | 改（扩展，保留现有 4 个测试） |
| `apps/api/tests/test_orchestrator.py` | 新建，测 astream_generate / astream_chat 透传 | 新建 |

---

## Task 0: 工程前置验证（基线绿 + 分支）

**Files:**
- 无文件改动，仅验证

- [ ] **Step 1: 确认基线测试全绿**

Run:
```bash
cd apps/api && uv run pytest -q 2>&1 | tail -10
```
Expected: 全绿（现有测试基线不破）。若有 failure，先停止本计划，修复基线再开工。

- [ ] **Step 2: 切到新分支（与用户确认分支策略后）**

本计划的改动与当前 `feat/firecrawl-web-ingestion` 分支的未提交改动（`knowledge_service.py` / `test_knowledge_service_url.py` / `ragflow spec`）主题不同。两种处理方式，**先与用户确认选哪种**：

方式 A（推荐）：暂存 firecrawl 改动 → 切 main → 开新分支
```bash
cd /g/03-Personal-Projects/TianGong
git stash push -u -m "firecrawl WIP（cross-section-context 开工前暂存）"
git checkout main
git checkout -b feat/cross-section-context
```

方式 B：在当前分支直接开工（spec 文件已在工作区，与 firecrawl 改动并存提交时分开 commit）

Expected: 新分支 `feat/cross-section-context` 创建并切换成功（方式 A），或确认留在当前分支（方式 B）。

- [ ] **Step 3: 确认目标文件当前内容（取证基线）**

Run:
```bash
cd apps/api && uv run python -c "
from app.ai.orchestrator import astream_generate, astream_chat
import inspect
src = inspect.getsource(astream_generate)
print('astream_generate history used:', 'history' in src and 'messages' in src)
print('astream_generate passes section:', 'section=section' in inspect.getsource(astream_generate))
"
```
Expected: 打印 `astream_generate history used: False`（当前 bug：history 收了没用）和 `astream_generate passes section: False`（当前 bug：不传 section）。**这是 bug 存在的证据，本计划完成后两个值应变 True。**

---

## Phase 1: 上下文装配函数（`context_assembler.py`）

### Task 1.1: 实现 `get_written_sections_text`（过滤 + 截断）

**Files:**
- Modify: `apps/api/app/ai/context_assembler.py`
- Test: `apps/api/tests/test_context.py`

- [ ] **Step 1: 写失败测试**

在 `apps/api/tests/test_context.py` 末尾追加（保留现有 4 个测试不动）：

```python
# ===== get_written_sections_text 测试 =====

def _tiptap(text: str) -> dict:
    """构造最小 Tiptap JSON（含一段 text）。"""
    return {
        "type": "doc",
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}],
    }


def _make_project(db_session) -> "Project":
    """构造一个真实入库的 Project。"""
    from app.models import Project
    p = Project(user_id=None, title="测试交底书")
    db_session.add(p)
    db_session.commit()
    db_session.refresh(p)
    return p


def _make_db_section(db_session, project_id, *, key, title, order, content=None) -> "Section":
    """构造一个真实入库的 Section。"""
    from app.models import Section
    s = Section(
        project_id=project_id,
        template_section_id=f"ts-{key}",
        order=order, key=key, title=title,
        content=content, status="drafting",
    )
    db_session.add(s)
    db_session.commit()
    db_session.refresh(s)
    return s


def test_get_written_sections_text_filters_empty_content(db_session):
    """content 为 None 的章节被跳过。"""
    from app.ai.context_assembler import get_written_sections_text
    p = _make_project(db_session)
    _make_db_section(db_session, p.id, key="name", title="发明名称", order=1, content=None)  # None，跳过
    _make_db_section(db_session, p.id, key="field", title="技术领域", order=2, content=_tiptap("机械领域"))  # 保留
    text = get_written_sections_text(db_session, p.id, exclude_key="background")
    assert "技术领域" in text
    assert "发明名称" not in text  # content=None 被跳过


def test_get_written_sections_text_orders_by_section_order(db_session):
    """按 Section.order 排序（不是按插入顺序）。"""
    from app.ai.context_assembler import get_written_sections_text
    p = _make_project(db_session)
    # 故意倒序插入
    _make_db_section(db_session, p.id, key="field", title="技术领域", order=2, content=_tiptap("BBB"))
    _make_db_section(db_session, p.id, key="name", title="发明名称", order=1, content=_tiptap("AAA"))
    text = get_written_sections_text(db_session, p.id, exclude_key="background")
    assert text.index("AAA") < text.index("BBB")  # name(order=1) 在 field(order=2) 前


def test_get_written_sections_text_excludes_current_section(db_session):
    """exclude_key 指定的当前章节被排除。"""
    from app.ai.context_assembler import get_written_sections_text
    p = _make_project(db_session)
    _make_db_section(db_session, p.id, key="name", title="发明名称", order=1, content=_tiptap("门锁"))
    text = get_written_sections_text(db_session, p.id, exclude_key="name")
    assert "门锁" not in text
    assert text == ""  # 只有 name，被排除后为空


def test_get_written_sections_text_truncates_at_budget(db_session, monkeypatch):
    """超 8000 字时截断 + 标注「（已截断）」。"""
    from app.ai import context_assembler
    # 把预算调小到 50 字，便于测试
    monkeypatch.setattr(context_assembler, "WRITTEN_SECTIONS_CHAR_BUDGET", 50)
    from app.ai.context_assembler import get_written_sections_text
    p = _make_project(db_session)
    long_text = "X" * 200  # 远超 50 字预算
    _make_db_section(db_session, p.id, key="name", title="发明名称", order=1, content=_tiptap(long_text))
    text = get_written_sections_text(db_session, p.id, exclude_key="background")
    assert "（已截断）" in text
    assert len(text) <= 200  # 截断后远小于原文 200 字


def test_get_written_sections_text_truncation_keeps_earlier_full(db_session, monkeypatch):
    """截断时前面章节保持完整，当前超长章截断。"""
    from app.ai import context_assembler
    monkeypatch.setattr(context_assembler, "WRITTEN_SECTIONS_CHAR_BUDGET", 100)
    from app.ai.context_assembler import get_written_sections_text
    p = _make_project(db_session)
    _make_db_section(db_session, p.id, key="name", title="发明名称", order=1, content=_tiptap("短章完整内容"))
    _make_db_section(db_session, p.id, key="field", title="技术领域", order=2, content=_tiptap("Y" * 200))  # 超长
    text = get_written_sections_text(db_session, p.id, exclude_key="background")
    assert "短章完整内容" in text  # name 完整保留
    assert "（已截断）" in text  # field 被截断
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_context.py -v -k "get_written_sections_text"`
Expected: FAIL（`ImportError: cannot import name 'get_written_sections_text' from 'app.ai.context_assembler'`）

- [ ] **Step 3: 实现 `get_written_sections_text` + `WRITTEN_SECTIONS_CHAR_BUDGET`**

在 `apps/api/app/ai/context_assembler.py` 顶部 import 区追加（`select` 已在 `get_project_summaries` 内局部导入，此处提到模块级）：

```python
from sqlalchemy import select
from app.services.summary_service import _extract_text
```

在文件末尾（`get_project_summaries` 之后）追加：

```python
# 前文注入字符软上限（T1 方案，spec §2.3 决策③）
# MVP 阶段无真实长文数据，覆盖 90% 场景；超长文场景等真实数据出现再做分块/滑动窗口
WRITTEN_SECTIONS_CHAR_BUDGET = 8000


def get_written_sections_text(db, project_id, exclude_key: str) -> str:
    """查询同项目所有非空章节（不论 status，排除当前章节），提取纯文本，截断到软上限。

    - 不论 status：drafting / confirmed 都注入（绕开 summary 的 confirmed 触发限制，spec §3.1.2）
    - content.isnot(None)：空章节跳过
    - 按 Section.order 装配，超 WRITTEN_SECTIONS_CHAR_BUDGET 时截断当前章并中止（保证前面章节完整）
    - 复用 summary_service._extract_text 提取 Tiptap JSON 纯文本（与 rag/archiver、review_service 同一既定模式）
    """
    sections = db.scalars(
        select(Section).where(
            (Section.project_id == project_id)
            & (Section.key != exclude_key)
            & (Section.content.isnot(None))
        ).order_by(Section.order)
    )
    parts: list[str] = []
    total = 0
    for s in sections:
        text = _extract_text(s.content).strip()
        if not text:
            continue
        chunk = f"## {s.title}\n{text}"
        if total + len(chunk) > WRITTEN_SECTIONS_CHAR_BUDGET:
            # 软上限：保留前面已装配的，当前章截断后中止
            remaining = WRITTEN_SECTIONS_CHAR_BUDGET - total
            if remaining > 100:  # 剩余空间太小就不塞半截
                parts.append(f"## {s.title}\n{text[:remaining]}\n…（已截断）")
            break
        parts.append(chunk)
        total += len(chunk)
    return "\n\n".join(parts)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_context.py -v -k "get_written_sections_text"`
Expected: 5 PASS

- [ ] **Step 5: 回归现有 context 测试**

Run: `cd apps/api && uv run pytest tests/test_context.py -v`
Expected: 全绿（新增 5 个 + 原有 4 个 = 9 PASS）

- [ ] **Step 6: 提交**

```bash
cd /g/03-Personal-Projects/TianGong
git add apps/api/app/ai/context_assembler.py apps/api/tests/test_context.py
git commit -m "feat(ai): get_written_sections_text 前文查询+截断（跨章节上下文 Task 1.1）"
```

---

### Task 1.2: 实现 `_format_metadata`（防御性格式化）

**Files:**
- Modify: `apps/api/app/ai/context_assembler.py`
- Test: `apps/api/tests/test_context.py`

- [ ] **Step 1: 写失败测试**

在 `apps/api/tests/test_context.py` 末尾追加：

```python
# ===== _format_metadata 测试 =====

def test_format_metadata_str_values():
    """字符串/数字值被格式化为 '- k：v' 行。"""
    from app.ai.context_assembler import _format_metadata
    out = _format_metadata({"技术领域": "机械", "关键词数": 3})
    assert "- 技术\uff1a机械" not in out  # 全角冒号在中文里用，但这里 key 不带冒号
    assert "- 技术领域：机械" in out
    assert "- 关键词数：3" in out


def test_format_metadata_skips_nested_structures():
    """嵌套 dict / list 被跳过（防御性，metadata 结构未定死）。"""
    from app.ai.context_assembler import _format_metadata
    out = _format_metadata({"正常": "值", "嵌套": {"a": 1}, "列表": [1, 2]})
    assert "- 正常：值" in out
    assert "嵌套" not in out
    assert "列表" not in out


def test_format_metadata_empty_returns_empty():
    """空 dict / None 返回空字符串。"""
    from app.ai.context_assembler import _format_metadata
    assert _format_metadata({}) == ""
    assert _format_metadata(None) == ""
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_context.py -v -k "_format_metadata"`
Expected: FAIL（`ImportError: cannot import name '_format_metadata'`）

- [ ] **Step 3: 实现 `_format_metadata`**

在 `apps/api/app/ai/context_assembler.py` 末尾（`get_written_sections_text` 之后）追加：

```python
def _format_metadata(metadata: dict | None) -> str:
    """格式化项目 metadata（JSON dict）为可读文本。防御性：只取字符串/数字值，跳过嵌套结构。

    metadata 结构未定死（Project.metadata_ 是自由 JSON），做防御性格式化避免
    嵌套 dict/list 把 system prompt 搞乱。spec §3.1.3。
    """
    if not isinstance(metadata, dict) or not metadata:
        return ""
    lines = []
    for k, v in metadata.items():
        if isinstance(v, (str, int, float)):
            lines.append(f"- {k}：{v}")
    return "\n".join(lines)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_context.py -v -k "_format_metadata"`
Expected: 3 PASS

- [ ] **Step 5: 回归现有 context 测试**

Run: `cd apps/api && uv run pytest tests/test_context.py -v`
Expected: 全绿（9 + 3 = 12 PASS）

- [ ] **Step 6: 提交**

```bash
cd /g/03-Personal-Projects/TianGong
git add apps/api/app/ai/context_assembler.py apps/api/tests/test_context.py
git commit -m "feat(ai): _format_metadata 防御性格式化项目 metadata（跨章节上下文 Task 1.2）"
```

---

### Task 1.3: 实现 `build_system_prompt`（装配总入口）

**Files:**
- Modify: `apps/api/app/ai/context_assembler.py`
- Test: `apps/api/tests/test_context.py`

- [ ] **Step 1: 写失败测试**

在 `apps/api/tests/test_context.py` 末尾追加：

```python
# ===== build_system_prompt 测试 =====

def test_build_system_prompt_includes_project_title(db_session):
    """[L4] system prompt 含项目标题。"""
    from app.ai.context_assembler import build_system_prompt
    from app.models import Section
    p = _make_project(db_session)
    p.title = "一种凸轮门锁"
    db_session.commit()
    s = _make_db_section(db_session, p.id, key="field", title="技术领域", order=2, content=None)
    prompt = build_system_prompt(db_session, s)
    assert "一种凸轮门锁" in prompt


def test_build_system_prompt_includes_metadata(db_session):
    """[L4] metadata 非空时被格式化注入。"""
    from app.ai.context_assembler import build_system_prompt
    from app.models import Project
    p = _make_project(db_session)
    p.metadata_ = {"技术领域": "机械", "阶段": "draft"}
    db_session.commit()
    s = _make_db_section(db_session, p.id, key="field", title="技术领域", order=2, content=None)
    prompt = build_system_prompt(db_session, s)
    assert "- 技术领域：机械" in prompt
    assert "- 阶段：draft" in prompt


def test_build_system_prompt_skips_empty_metadata(db_session):
    """[L4] metadata 为 None 时不报错、不留空段。"""
    from app.ai.context_assembler import build_system_prompt
    p = _make_project(db_session)
    # metadata_ 默认 None
    s = _make_db_section(db_session, p.id, key="field", title="技术领域", order=2, content=None)
    prompt = build_system_prompt(db_session, s)
    assert "项目背景信息" not in prompt  # 不留空段标题
    assert "测试交底书" in prompt  # 标题仍在


def test_build_system_prompt_includes_current_section_strategy(db_session):
    """含当前章节 goal + output_format。"""
    from app.ai.context_assembler import build_system_prompt
    from app.ai.section_prompts import get_section_prompt
    p = _make_project(db_session)
    s = _make_db_section(db_session, p.id, key="solution", title="技术方案", order=5, content=None)
    prompt = build_system_prompt(db_session, s)
    sp = get_section_prompt("solution")
    assert sp.goal in prompt
    assert sp.output_format in prompt
    assert "技术方案" in prompt


def test_build_system_prompt_includes_written_sections(db_session):
    """[前文注入] 含已写章节标题 + 内容。"""
    from app.ai.context_assembler import build_system_prompt
    p = _make_project(db_session)
    _make_db_section(db_session, p.id, key="name", title="发明名称", order=1, content=_tiptap("凸轮门锁"))
    s = _make_db_section(db_session, p.id, key="field", title="技术领域", order=2, content=None)
    prompt = build_system_prompt(db_session, s)
    assert "发明名称" in prompt
    assert "凸轮门锁" in prompt


def test_build_system_prompt_excludes_current_section_from_written(db_session):
    """已写章节段不含当前章节自身。"""
    from app.ai.context_assembler import build_system_prompt
    p = _make_project(db_session)
    # 当前章节 field 自己有 content，但不应出现在「已完成章节」段
    s = _make_db_section(db_session, p.id, key="field", title="技术领域", order=2, content=_tiptap("我自己"))
    prompt = build_system_prompt(db_session, s)
    assert "我自己" not in prompt


def test_build_system_prompt_includes_system_prompt_role(db_session):
    """末尾含 SYSTEM_PROMPT 角色定义。"""
    from app.ai.context_assembler import build_system_prompt, SYSTEM_PROMPT
    p = _make_project(db_session)
    s = _make_db_section(db_session, p.id, key="field", title="技术领域", order=2, content=None)
    prompt = build_system_prompt(db_session, s)
    assert SYSTEM_PROMPT in prompt  # 角色定义拼接在末尾


def test_build_system_prompt_first_chapter_no_written(db_session):
    """第一章时跳过「已完成章节」段，不报错。"""
    from app.ai.context_assembler import build_system_prompt
    p = _make_project(db_session)
    # 只有当前章节 name，无其他非空章节
    s = _make_db_section(db_session, p.id, key="name", title="发明名称", order=1, content=None)
    prompt = build_system_prompt(db_session, s)
    assert "已完成章节" not in prompt  # 无前文，跳过该段
    assert "测试交底书" in prompt  # 项目标题仍在
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_context.py -v -k "build_system_prompt"`
Expected: FAIL（`ImportError: cannot import name 'build_system_prompt'`）

- [ ] **Step 3: 实现 `build_system_prompt`**

在 `apps/api/app/ai/context_assembler.py` 顶部 import 区，把现有的 `from app.models import Message, Section` 扩展为也导入 `Project`：

```python
from app.models import Message, Project, Section
```

在文件末尾追加（依赖 Task 1.1 的 `get_written_sections_text` + Task 1.2 的 `_format_metadata`）：

```python
def build_system_prompt(db, section: Section) -> str:
    """装配动态 system prompt（agent loop 路线用，spec §3.1.1）。

    拼接顺序：项目元信息 [L4] → 已写章节 [前文直注入] → 当前章节策略 → 角色定义。

    项目元信息在顶部（全局不变量先建立上下文），角色定义在底部（行为规范在看到具体任务后理解更准确）。
    此顺序与原 assemble_messages 的拼接顺序保持心智模型统一。
    """
    project = db.get(Project, section.project_id)
    sp = get_section_prompt(section.key)

    parts: list[str] = []

    # [L4] 项目元信息层（顶部，全局上下文）
    parts.append("# 当前交底书项目")
    parts.append(f"项目标题：{project.title}")
    if project.metadata_:
        meta_text = _format_metadata(project.metadata_)
        if meta_text:
            parts.append(f"项目背景信息：\n{meta_text}")

    # [前文直注入] 已写章节层（中部，跨章节上下文）
    written = get_written_sections_text(db, section.project_id, exclude_key=section.key)
    if written:
        parts.append("# 已完成章节内容（请保持术语、技术方案一致性）")
        parts.append(written)

    # 章节策略层（底部偏上，当前章节聚焦）
    parts.append("# 当前正在撰写章节")
    parts.append(f"章节标题：【{section.title}】")
    parts.append(f"本章目标：{sp.goal}")
    parts.append(f"输出格式要求：{sp.output_format}")

    # 角色定义层（最底部，兜底规范）
    parts.append(SYSTEM_PROMPT)

    return "\n\n".join(parts)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_context.py -v -k "build_system_prompt"`
Expected: 8 PASS

- [ ] **Step 5: 回归全量 context 测试**

Run: `cd apps/api && uv run pytest tests/test_context.py -v`
Expected: 全绿（12 + 8 = 20 PASS）

- [ ] **Step 6: 提交**

```bash
cd /g/03-Personal-Projects/TianGong
git add apps/api/app/ai/context_assembler.py apps/api/tests/test_context.py
git commit -m "feat(ai): build_system_prompt 装配动态上下文（跨章节上下文 Task 1.3，L4+前文直注入）"
```

---

## Phase 1 收尾检查

- [ ] `context_assembler.py` 新增 3 个函数 + 1 个常量，现有 `assemble_messages` / `get_project_summaries` / `SYSTEM_PROMPT` 零改动
- [ ] `test_context.py` 新增 16 个测试全绿，原有 4 个测试零回归
- [ ] `get_written_sections_text` 不论 status 注入（drafting / confirmed 都进），content=None 跳过
- [ ] `build_system_prompt` 顺序：项目元信息 → 已写章节 → 章节策略 → 角色定义

---

## Phase 2: Agent 工厂扩展（`agent.py`）

### Task 2.1: 扩展 `build_agent` 签名，section 非 None 时调 `build_system_prompt`

**Files:**
- Modify: `apps/api/app/ai/agent.py`
- Test: `apps/api/tests/test_agent_factory.py`

- [ ] **Step 1: 写失败测试**

在 `apps/api/tests/test_agent_factory.py` 末尾追加（保留现有 4 个测试不动）。需要先构造一个带 Project 的真实 Section，复用 `db_session` fixture：

```python
# ===== build_agent 传 section 测试 =====

def _build_section_with_project(db_session):
    """构造一个真实入库的 Project + Section，供 build_agent 的 section 参数用。"""
    from app.models import Project, Section
    p = Project(user_id=None, title="凸轮门锁交底书")
    db_session.add(p)
    db_session.commit()
    db_session.refresh(p)
    s = Section(
        project_id=p.id,
        template_section_id="ts-field",
        order=2, key="field", title="技术领域",
        content=None, status="empty",
    )
    db_session.add(s)
    db_session.commit()
    db_session.refresh(s)
    return s


def test_build_agent_with_section_uses_dynamic_prompt(db_session, monkeypatch):
    """传 section 时，create_deep_agent 收到的 system_prompt 含项目标题 + 章节策略。"""
    from app.ai import agent as agent_mod
    from app.services.llm_config_service import ResolvedChatConfig

    section = _build_section_with_project(db_session)
    captured: dict = {}

    def _fake_create(model=None, tools=None, *, system_prompt=None, **kw):
        captured["system_prompt"] = system_prompt
        return type("_S", (), {"ainvoke": lambda *a: None, "astream_events": lambda *a: None})()

    monkeypatch.setattr(agent_mod, "get_llm", lambda config, **kw: _mock_llm())
    monkeypatch.setattr(agent_mod, "create_deep_agent", _fake_create)
    from app.core import storage as storage_mod

    class _FakeStorage:
        def __init__(self): self._client = None
        def _resolve(self, a): return a
    monkeypatch.setattr(storage_mod, "get_storage", lambda: _FakeStorage())

    config = ResolvedChatConfig(base_url="http://x", api_key="k", model="glm-4.7", source="env")
    agent_mod.build_agent(db_session, llm_config=config, user_id=uuid.uuid4(), section=section)

    # 动态 prompt 含项目标题（来自 build_system_prompt）
    assert "凸轮门锁交底书" in captured["system_prompt"]
    # 含当前章节策略
    assert "技术领域" in captured["system_prompt"]


def test_build_agent_without_section_falls_back_to_static(db_session, monkeypatch):
    """不传 section 时，system_prompt == SYSTEM_PROMPT（向后兼容）。"""
    from app.ai import agent as agent_mod
    from app.ai.context_assembler import SYSTEM_PROMPT
    from app.services.llm_config_service import ResolvedChatConfig

    captured: dict = {}

    def _fake_create(model=None, tools=None, *, system_prompt=None, **kw):
        captured["system_prompt"] = system_prompt
        return type("_S", (), {"ainvoke": lambda *a: None, "astream_events": lambda *a: None})()

    monkeypatch.setattr(agent_mod, "get_llm", lambda config, **kw: _mock_llm())
    monkeypatch.setattr(agent_mod, "create_deep_agent", _fake_create)
    from app.core import storage as storage_mod

    class _FakeStorage:
        def __init__(self): self._client = None
        def _resolve(self, a): return a
    monkeypatch.setattr(storage_mod, "get_storage", lambda: _FakeStorage())

    config = ResolvedChatConfig(base_url="http://x", api_key="k", model="glm-4.7", source="env")
    agent_mod.build_agent(db_session, llm_config=config, user_id=uuid.uuid4())  # 不传 section

    assert captured["system_prompt"] == SYSTEM_PROMPT


def test_build_agent_with_section_prompt_not_equal_static(db_session, monkeypatch):
    """动态 prompt 与静态 SYSTEM_PROMPT 不同（防回归：确保真的走了 build_system_prompt）。"""
    from app.ai import agent as agent_mod
    from app.ai.context_assembler import SYSTEM_PROMPT
    from app.services.llm_config_service import ResolvedChatConfig

    section = _build_section_with_project(db_session)
    captured: dict = {}

    def _fake_create(model=None, tools=None, *, system_prompt=None, **kw):
        captured["system_prompt"] = system_prompt
        return type("_S", (), {"ainvoke": lambda *a: None, "astream_events": lambda *a: None})()

    monkeypatch.setattr(agent_mod, "get_llm", lambda config, **kw: _mock_llm())
    monkeypatch.setattr(agent_mod, "create_deep_agent", _fake_create)
    from app.core import storage as storage_mod

    class _FakeStorage:
        def __init__(self): self._client = None
        def _resolve(self, a): return a
    monkeypatch.setattr(storage_mod, "get_storage", lambda: _FakeStorage())

    config = ResolvedChatConfig(base_url="http://x", api_key="k", model="glm-4.7", source="env")
    agent_mod.build_agent(db_session, llm_config=config, user_id=uuid.uuid4(), section=section)

    assert captured["system_prompt"] != SYSTEM_PROMPT
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_agent_factory.py -v -k "with_section or without_section"`
Expected: FAIL（`TypeError: build_agent() got an unexpected keyword argument 'section'`）

- [ ] **Step 3: 扩展 `build_agent` 签名**

修改 `apps/api/app/ai/agent.py` 的 `build_agent` 函数。

**改动 1**：函数签名加 `section` 参数（`agent.py:37-39`）：

```python
def build_agent(
    db, *, llm_config: ResolvedChatConfig, user_id,
    section: "Section | None" = None,  # ← 新增。延迟注解避免循环 import
) -> CompiledStateGraph:
```

**改动 2**：docstring 的 Args 段加 `section` 说明（`agent.py:62-71` 附近，在 `user_id:` 之后、`Returns:` 之前插入）：

```
        section: 当前要撰写/对话的 Section。非 None 时调 build_system_prompt 装配
            动态 system prompt（含项目标题、已写章节、章节策略）。None 时用
            静态 SYSTEM_PROMPT 兜底（向后兼容，本 spec 范围内 chat/generate 都会传 section）。
```

**改动 3**：在 `llm = get_llm(llm_config, streaming=True)`（`agent.py:97`）之后、`create_deep_agent(...)`（`agent.py:100`）之前插入动态 prompt 装配逻辑：

```python
    # [L1][L4][前文直注入] section 非 None 时装配动态 system prompt（spec §3.2）
    if section is not None:
        from app.ai.context_assembler import build_system_prompt
        system_prompt = build_system_prompt(db, section)
    else:
        system_prompt = SYSTEM_PROMPT  # 向后兼容兜底
```

**改动 4**：把 `create_deep_agent(...)` 调用里的 `system_prompt=SYSTEM_PROMPT` 改为 `system_prompt=system_prompt`（`agent.py:102`）：

```python
    agent = create_deep_agent(
        model=llm,  # I1：不预绑定。deepagents 内部调 bind_tools，预绑定会让 RunnableBinding 无 bind_tools 方法。
        system_prompt=system_prompt,  # ← 改：用动态装配的变量
        tools=[rag_search_tool],
        skills=skill_sources if skill_sources else None,
        backend=backend,
        store=store,
    )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_agent_factory.py -v -k "with_section or without_section"`
Expected: 3 PASS

- [ ] **Step 5: 回归现有 agent_factory 测试**

Run: `cd apps/api && uv run pytest tests/test_agent_factory.py -v`
Expected: 全绿（4 + 3 = 7 PASS）

- [ ] **Step 6: 提交**

```bash
cd /g/03-Personal-Projects/TianGong
git add apps/api/app/ai/agent.py apps/api/tests/test_agent_factory.py
git commit -m "feat(ai): build_agent 扩展 section 参数装配动态 system prompt（跨章节上下文 Task 2.1）"
```

---

## Phase 2 收尾检查

- [ ] `build_agent` 签名 `(db, *, llm_config, user_id, section=None)`
- [ ] section 非 None 时调 `build_system_prompt`，None 时用 `SYSTEM_PROMPT` 兜底
- [ ] 现有 4 个 agent_factory 测试零回归（`test_build_agent_returns_compiled_graph` 等不传 section 仍能跑通）

---

## Phase 3: Orchestrator 改造（`orchestrator.py`）

### Task 3.1: `astream_generate` 传 section + 透传 history

**Files:**
- Modify: `apps/api/app/ai/orchestrator.py`
- Test: `apps/api/tests/test_orchestrator.py`（新建）

- [ ] **Step 1: 写失败测试（新建测试文件）**

创建 `apps/api/tests/test_orchestrator.py`：

```python
# apps/api/tests/test_orchestrator.py
"""astream_generate / astream_chat 透传 section + history 测试（跨章节上下文 L1+L2）。

策略：mock build_agent 返回 fake agent，用 captured 捕获 build_agent 收到的参数
和 agent.astream_events 收到的 messages。不真实调 LLM、不真实建 agent。
参考 test_llm_config_e2e.py 的 _fake_agent_factory 模式。
"""
import uuid

import pytest


def _build_section_with_project(db_session):
    """构造真实入库的 Project + Section。"""
    from app.models import Project, Section
    p = Project(user_id=None, title="透传测试项目")
    db_session.add(p)
    db_session.commit()
    db_session.refresh(p)
    s = Section(
        project_id=p.id,
        template_section_id="ts-solution",
        order=5, key="solution", title="技术方案",
        content=None, status="empty",
    )
    db_session.add(s)
    db_session.commit()
    db_session.refresh(s)
    return s


def _fake_agent_factory(captured: dict):
    """返回一个 fake build_agent：捕获调用参数，返回假 agent。

    假 agent 的 astream_events 捕获收到的 messages，然后直接 StopAsyncIteration。
    """

    class _FakeAgent:
        def __init__(self, build_args):
            self._build_args = build_args

        async def astream_events(self, input_, *, version="v2"):
            captured["astream_input"] = input_
            return
            yield  # 让它成为 async generator

    def _build_agent(db, *, llm_config, user_id, section=None, **kw):
        captured["build_args"] = {"section": section, "user_id": user_id, "llm_config": llm_config}
        return _FakeAgent(captured.get("astream_input", {}))

    return _build_agent


@pytest.mark.asyncio
async def test_astream_generate_passes_section_to_build_agent(db_session, monkeypatch):
    """[L1] build_agent 收到 section 参数。"""
    from app.ai import orchestrator as orch_mod
    from app.services.llm_config_service import ResolvedChatConfig

    section = _build_section_with_project(db_session)
    captured: dict = {}
    monkeypatch.setattr(orch_mod, "build_agent", _fake_agent_factory(captured))

    config = ResolvedChatConfig(base_url="http://x", api_key="k", model="glm-4.7", source="env")
    # 消费 async generator
    async for _ in orch_mod.astream_generate(db_session, section, [], llm_config=config):
        pass

    assert captured["build_args"]["section"] is section  # 同一对象


@pytest.mark.asyncio
async def test_astream_generate_passes_history_to_agent_messages(db_session, monkeypatch):
    """[L2] agent.astream_events 收到 history + instruction。"""
    from app.ai import orchestrator as orch_mod
    from app.models import Message
    from app.services.llm_config_service import ResolvedChatConfig

    section = _build_section_with_project(db_session)
    history = [
        Message(section_id=section.id, role="user", content="前面问的"),
        Message(section_id=section.id, role="assistant", content="前面答的"),
    ]
    captured: dict = {}
    monkeypatch.setattr(orch_mod, "build_agent", _fake_agent_factory(captured))

    config = ResolvedChatConfig(base_url="http://x", api_key="k", model="glm-4.7", source="env")
    async for _ in orch_mod.astream_generate(db_session, section, history, llm_config=config):
        pass

    messages = captured["astream_input"]["messages"]
    # history 2 条 + instruction 1 条 = 3 条
    assert len(messages) == 3
    assert messages[0] == {"role": "user", "content": "前面问的"}
    assert messages[1] == {"role": "assistant", "content": "前面答的"}
    assert "技术方案" in messages[2]["content"]  # instruction 含章节标题


@pytest.mark.asyncio
async def test_astream_generate_empty_history_only_instruction(db_session, monkeypatch):
    """[L2] history 为空时 messages 只有 instruction。"""
    from app.ai import orchestrator as orch_mod
    from app.services.llm_config_service import ResolvedChatConfig

    section = _build_section_with_project(db_session)
    captured: dict = {}
    monkeypatch.setattr(orch_mod, "build_agent", _fake_agent_factory(captured))

    config = ResolvedChatConfig(base_url="http://x", api_key="k", model="glm-4.7", source="env")
    async for _ in orch_mod.astream_generate(db_session, section, [], llm_config=config):
        pass

    messages = captured["astream_input"]["messages"]
    assert len(messages) == 1  # 只有 instruction
```

- [ ] **Step 2: 确认 pytest-asyncio 可用**

Run: `cd apps/api && uv run pytest --collect-only tests/test_orchestrator.py 2>&1 | head -20`
Expected: 能收集到 3 个 async 测试。若报 `pytest-asyncio` 未装，先检查 `pyproject.toml` 是否已有该依赖（项目已有 async 测试如 `test_ai.py`，应该装了）。若收集失败，参考现有 async 测试的 marker 写法。

- [ ] **Step 3: 跑测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_orchestrator.py -v`
Expected: FAIL（`assert captured["build_args"]["section"] is section` 失败——当前 `astream_generate` 不传 section，build_agent 收到的是默认 None；或 messages 长度不对——当前不透传 history）

- [ ] **Step 4: 改造 `astream_generate`**

修改 `apps/api/app/ai/orchestrator.py` 的 `astream_generate` 函数（`orchestrator.py:127-175`）。

**改动 1**：`build_agent(...)` 调用加 `section=section`（`orchestrator.py:148`）：

```python
    agent = build_agent(db, llm_config=llm_config, user_id=_section_owner(db, section), section=section)
```

**改动 2**：把原来只传 instruction 的 `astream_events({"messages": [{"role": "user", "content": instruction}]}, ...)`（`orchestrator.py:154-156`）改为透传 history + instruction：

```python
    # [L2] 透传本章节对话历史（spec §3.3.1）
    messages = []
    for msg in history:
        messages.append({"role": msg.role, "content": msg.content})
    messages.append({"role": "user", "content": instruction})

    async for event in agent.astream_events({"messages": messages}, version="v2"):
```

注意：`messages.append(...)` 这几行要放在 `instruction = ...` 定义之后、`async for event in agent.astream_events(...)` 之前。把原来的 `agent.astream_events({"messages": [{"role": "user", "content": instruction}]}, ...)` 整体替换掉。

- [ ] **Step 5: 跑测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_orchestrator.py -v`
Expected: 3 PASS

- [ ] **Step 6: 回归现有 AI 测试**

Run: `cd apps/api && uv run pytest tests/test_ai.py tests/test_llm_config_e2e.py tests/test_llm_token_logging.py -v 2>&1 | tail -20`
Expected: 全绿（这些测试 mock 的是 `astream_*` 本身，不触达 build_agent，应该不受影响）

- [ ] **Step 7: 提交**

```bash
cd /g/03-Personal-Projects/TianGong
git add apps/api/app/ai/orchestrator.py apps/api/tests/test_orchestrator.py
git commit -m "feat(ai): astream_generate 传 section + 透传 history（跨章节上下文 Task 3.1，L1+L2）"
```

---

### Task 3.2: `astream_chat` 对称改造

**Files:**
- Modify: `apps/api/app/ai/orchestrator.py`
- Test: `apps/api/tests/test_orchestrator.py`

- [ ] **Step 1: 写失败测试**

在 `apps/api/tests/test_orchestrator.py` 末尾追加：

```python
# ===== astream_chat 测试 =====

@pytest.mark.asyncio
async def test_astream_chat_passes_section_to_build_agent(db_session, monkeypatch):
    """[L1] chat 路径：build_agent 收到 section 参数。"""
    from app.ai import orchestrator as orch_mod
    from app.services.llm_config_service import ResolvedChatConfig

    section = _build_section_with_project(db_session)
    captured: dict = {}
    monkeypatch.setattr(orch_mod, "build_agent", _fake_agent_factory(captured))

    config = ResolvedChatConfig(base_url="http://x", api_key="k", model="glm-4.7", source="env")
    async for _ in orch_mod.astream_chat(db_session, section, [], "用户问题", llm_config=config):
        pass

    assert captured["build_args"]["section"] is section


@pytest.mark.asyncio
async def test_astream_chat_passes_history_and_user_input(db_session, monkeypatch):
    """[L2] chat 透传 history + user_input。"""
    from app.ai import orchestrator as orch_mod
    from app.models import Message
    from app.services.llm_config_service import ResolvedChatConfig

    section = _build_section_with_project(db_session)
    history = [
        Message(section_id=section.id, role="user", content="历史问"),
        Message(section_id=section.id, role="assistant", content="历史答"),
    ]
    captured: dict = {}
    monkeypatch.setattr(orch_mod, "build_agent", _fake_agent_factory(captured))

    config = ResolvedChatConfig(base_url="http://x", api_key="k", model="glm-4.7", source="env")
    async for _ in orch_mod.astream_chat(db_session, section, history, "当前问题", llm_config=config):
        pass

    messages = captured["astream_input"]["messages"]
    # history 2 条 + user_input 1 条 = 3 条
    assert len(messages) == 3
    assert messages[0] == {"role": "user", "content": "历史问"}
    assert messages[1] == {"role": "assistant", "content": "历史答"}
    assert messages[2] == {"role": "user", "content": "当前问题"}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_orchestrator.py -v -k "astream_chat"`
Expected: FAIL（`assert captured["build_args"]["section"] is section` 失败——当前 `astream_chat` 不传 section）

- [ ] **Step 3: 改造 `astream_chat`**

修改 `apps/api/app/ai/orchestrator.py` 的 `astream_chat` 函数（`orchestrator.py:81-124`）。改动与 Task 3.1 对称：

**改动 1**：`build_agent(...)` 调用加 `section=section`（`orchestrator.py:102`）：

```python
    agent = build_agent(db, llm_config=llm_config, user_id=_section_owner(db, section), section=section)
```

**改动 2**：把原来的 `agent.astream_events({"messages": [{"role": "user", "content": user_input}]}, ...)`（`orchestrator.py:103-106`）改为透传 history + user_input：

```python
    # [L2] 透传历史 + 当前用户输入（spec §3.3.2）
    messages = []
    for msg in history:
        messages.append({"role": msg.role, "content": msg.content})
    messages.append({"role": "user", "content": user_input})

    async for event in agent.astream_events({"messages": messages}, version="v2"):
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_orchestrator.py -v -k "astream_chat"`
Expected: 2 PASS

- [ ] **Step 5: 回归全量 orchestrator 测试**

Run: `cd apps/api && uv run pytest tests/test_orchestrator.py -v`
Expected: 全绿（3 + 2 = 5 PASS）

- [ ] **Step 6: 回归现有 AI 测试**

Run: `cd apps/api && uv run pytest tests/test_ai.py tests/test_llm_config_e2e.py tests/test_llm_token_logging.py -q 2>&1 | tail -10`
Expected: 全绿

- [ ] **Step 7: 提交**

```bash
cd /g/03-Personal-Projects/TianGong
git add apps/api/app/ai/orchestrator.py apps/api/tests/test_orchestrator.py
git commit -m "feat(ai): astream_chat 对称改造传 section + 透传 history（跨章节上下文 Task 3.2）"
```

---

## Phase 3 收尾检查

- [ ] `astream_generate` 和 `astream_chat` 都传 `section=section` 给 `build_agent`
- [ ] 两者都透传 `history`（展开成 messages 列表 + 当前指令）
- [ ] `astream_rewrite` 未改动（走 `astream_llm` 直连路径，不需跨章上下文）
- [ ] 5 个 orchestrator 测试全绿，现有 AI 测试集零回归

---

## Phase 4: 回归与集成验证

### Task 4.1: 跑全量测试确认无回归

**Files:**
- 无文件改动，仅验证

- [ ] **Step 1: 跑全量 AI 相关测试**

Run:
```bash
cd apps/api && uv run pytest tests/test_context.py tests/test_agent_factory.py tests/test_orchestrator.py tests/test_ai.py tests/test_ai_endpoints_chat_source.py tests/test_llm_config_e2e.py tests/test_llm_token_logging.py tests/test_caption.py tests/test_conversation_title.py -v 2>&1 | tail -40
```
Expected: 全绿

- [ ] **Step 2: 跑全量测试套件**

Run: `cd apps/api && uv run pytest -q 2>&1 | tail -15`
Expected: 全绿（基线 + 本计划新增的 24 个测试：context 16 + agent_factory 3 + orchestrator 5）

- [ ] **Step 3: 取证验证 bug 已修复**

Run:
```bash
cd apps/api && uv run python -c "
from app.ai.orchestrator import astream_generate
import inspect
src = inspect.getsource(astream_generate)
print('astream_generate history used:', 'for msg in history' in src)
print('astream_generate passes section:', 'section=section' in src)
"
```
Expected: 两个值都为 `True`（与 Task 0 Step 3 的 `False` 对比，证明 bug 已修复）

- [ ] **Step 4: 提交（无代码改动，标记验证完成）**

```bash
cd /g/03-Personal-Projects/TianGong
git commit --allow-empty -m "test(api): 跨章节上下文全量验证通过（L1+L2+L4+前文直注入）"
```

---

### Task 4.2: 手动 dogfood（真实流程验证）

**Files:**
- 无文件改动，手动验证

- [ ] **Step 1: 启动后端 + 配置 LLM**

```bash
cd apps/api && uv run python -m scripts.init_db  # 确保表结构最新
cd apps/api && uv run uvicorn app.main:app --reload
```
配 LLM（用全局配置或自定义配置，参考 GOTCHAS G1）。

- [ ] **Step 2: 走真实撰写流程验证「不失忆」**

操作步骤（用前端 `apps/web` 或 API 直调）：
1. 新建项目，标题填「一种基于凸轮机构的智能门锁」
2. 进入「发明名称」章节，写个内容（如"一种基于凸轮机构的智能门锁，涉及机械锁具领域"），确认
3. 进入「技术领域」章节，**不要重复说明项目背景**，直接点"生成草稿"
4. 观察生成的草稿

**验收标准**（spec §8）：
- 生成的草稿**明确引用了发明名称里的技术方向**（如提到"门锁""凸轮""机械"），证明 AI 看到了前文
- 草稿符合「技术领域」章节的输出格式要求

**反例（bug 未修复的表现）**：
- 草稿泛泛而谈，不知道在写什么领域（如"本发明涉及一种技术领域..."）
- 草稿要求用户重新说明项目背景

- [ ] **Step 3: 验证 chat 路径不失忆**

在「技术领域」章节的对话框里，**不重复项目背景**，直接问"我这个发明属于哪个 IPC 分类？"
验收：AI 能基于项目标题 + 已写章节回答（如提到"机械锁具""E05B"等），而非反问"你写的是什么发明？"

- [ ] **Step 4: 把 dogfood 发现的问题记入 GOTCHAS.md（若有）**

若发现新坑（如 token 超限、metadata 格式异常等），追加到 `docs/GOTCHAS.md`。

- [ ] **Step 5: 最终提交（dogfood 记录）**

若有 GOTCHAS 更新：
```bash
cd /g/03-Personal-Projects/TianGong
git add docs/GOTCHAS.md
git commit -m "docs(gotchas): 跨章节上下文 dogfood 记录"
```

---

## Self-Review 记录

### Spec 覆盖核对

对照 spec §1.1 的 4 项修复逐项检查：

| 修复项 | 实现位置（Task） | 状态 |
|---|---|---|
| **L1** astream_chat/generate 接回上下文装配 | Task 3.1（generate 传 section）+ Task 3.2（chat 传 section）+ Task 2.1（build_agent 装配） | ✅ |
| **L2** 透传本章节 history | Task 3.1（generate 透传）+ Task 3.2（chat 透传） | ✅ |
| **L4** 项目元信息注入 | Task 1.3（build_system_prompt 装配项目标题 + metadata）+ Task 1.2（_format_metadata） | ✅ |
| **前文直注入**（不走 summary） | Task 1.1（get_written_sections_text）+ Task 1.3（build_system_prompt 调用） | ✅ |

### 关键架构决策核对

| 决策（spec §2.3） | 实现位置 | 状态 |
|---|---|---|
| ① 走每次重建 agent，不引入 deepagents 中间件 | Task 2.1（build_agent 仍每次重建，无 lru_cache） | ✅ |
| ② 前文走原文直注入，不走 summary | Task 1.1（get_written_sections_text 调 _extract_text，不调 summary） | ✅ |
| ③ 前文 8000 字软上限 | Task 1.1（WRITTEN_SECTIONS_CHAR_BUDGET = 8000） | ✅ |
| ④ build_agent 扩展 section 参数 | Task 2.1 | ✅ |

### 边界情况覆盖（spec §4）

| 边界情况 | 测试用例 | 状态 |
|---|---|---|
| 4.1 token 超限 | 不做预防性测试（YAGNI，等真实遇到） | ✅ 按设计跳过 |
| 4.2 项目无 metadata | `test_build_system_prompt_skips_empty_metadata` | ✅ |
| 4.3 当前章节是第一章 | `test_build_system_prompt_first_chapter_no_written` | ✅ |
| 4.4 history 为空 | `test_astream_generate_empty_history_only_instruction` | ✅ |
| 4.5 章节 content 是无效 Tiptap JSON | 不单独测试（_extract_text 递归 walk 已防御，返回空被跳过） | ✅ 按设计跳过 |

### 不变量保护

- `assemble_messages` / `get_project_summaries` / `SYSTEM_PROMPT` 零改动（旧路径 `stream_*` 保留作参考）→ `test_context.py` 原 4 个测试零回归
- `astream_rewrite` 未改动 → 不影响 rewrite 端点
- `build_agent` 向后兼容（section=None 兜底）→ 现有 `test_build_agent_returns_compiled_graph` 等不传 section 仍跑通

### 已知限制（透明，对应 spec §7）

1. **8000 字软上限对极小 context 模型可能超限**：本计划不做预防，等真实遇到再优化（YAGNI）
2. **前文分块/滑动窗口未实现**：等真实长文（>8000 字前文）出现再做（进 backlog）
3. **旧路径 `stream_*` + `get_project_summaries` 成为死代码**：保留作参考，未来清理时一并删除

### 占位符扫描

- 无 "TBD"/"TODO"/"fill in" —— ✅
- 所有代码块含完整实现 —— ✅
- 所有 Run 命令含 Expected —— ✅
- 无 "Similar to Task N" 省略 —— ✅

---

## 实施顺序总结

| Phase | Tasks | 核心产出 | 测试新增 |
|---|---|---|---|
| 0 | Task 0 | 基线绿 + 分支 + bug 取证 | 0 |
| 1 | Task 1.1-1.3 | context_assembler 3 个新函数（前文查询+截断、metadata 格式化、prompt 装配总入口） | 16 |
| 2 | Task 2.1 | build_agent 扩展 section 参数 | 3 |
| 3 | Task 3.1-3.2 | astream_generate/chat 传 section + 透传 history | 5 |
| 4 | Task 4.1-4.2 | 全量回归 + dogfood | 0 |

**新增测试合计：24 个**（context 16 + agent_factory 3 + orchestrator 5）

**预计工期：3-4 天**（spec §0 锚点：纯后端、无迁移、无依赖、3 个文件改动 + 1 个新建测试文件）

---

## 附录：grill 决策如何映射到本计划

本计划源自 8 轮 `/grilling` 会话，关键决策在本计划中的落地：

| grill 决策 | 本计划落地 |
|---|---|
| Q4：痛点是病 A（AI 没看到原文） | Task 1.1 `get_written_sections_text` 直注入原文，不走 summary |
| Q5：选方案 D（前文直注入） | Phase 1 全部围绕"前文直注入"展开 |
| Q11/Q12：审阅侧进 backlog | 本计划零审阅侧改动，纯撰写侧 |
| Q13：T1 方案（8000 字软上限） | Task 1.1 `WRITTEN_SECTIONS_CHAR_BUDGET = 8000` |
| Q13：build_agent 扩展 section 参数 | Task 2.1 |
