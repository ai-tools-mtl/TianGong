# 计划 4：AI 撰写引擎 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** 实现天工核心 AI 能力——LLM 接入（GLM-5.2）、章节 Prompt 注册表、五层上下文装配、流式 SSE（引导对话/生成草稿/段落重写）、跨章节 summary，让用户能在编辑器里与 AI 对话撰写交底书。

**Architecture:** 后端用 `ChatOpenAI`（OpenAI 兼容协议）接入 GLM。AI 能力不引入 LangGraph（MVP 简化为直接 service 调用 + SSE 流式；LangGraph 状态机在计划 7 审查引擎时引入，那时才需要 Checkpoint/Store）。章节 Prompt 注册表定义 8 种章节的引导策略。流式用 FastAPI `StreamingResponse` + `text/event-stream`。

**Tech Stack:** langchain-openai（ChatOpenAI）· FastAPI StreamingResponse（SSE）· GLM-4-Flash（glm-4-flash 模型，OpenAI 兼容）

**Spec reference:** 设计文档 v1.5 第 5 章（AI 编排引擎）
- 5.4 上下文装配（五层：系统/知识库/项目/章节/对话）
- 5.5 章节 Prompt 注册表（SectionPromptRegistry）
- 5.6 AI 输出 Markdown → 后端转 Tiptap
- 5.7 流式 SSE 协议
- 5.8 三种 AI 行为（引导对话/生成草稿/段落重写）
- 5.10 跨章节 summary

**已验证:** GLM-4-Flash API key 有效，流式输出正常（19 chunks/短回复）。

---

## 关键设计决策（本计划）

1. **MVP 不用 LangGraph**：撰写流程的 AI 调用是请求-响应式的（用户提问→AI 流式回复），不需要状态机。LangGraph 留给计划 7（审查引擎需要 Checkpoint/Store 解决跨对话稳定）。这大幅降低计划 4 复杂度。
2. **LLM 抽象**：`LLMClient` 封装 `ChatOpenAI`，从 settings 读 GLM 配置。后续计划 7 的 BYOK 在此基础上扩展。
3. **Markdown→Tiptap 转换**：生成草稿时 AI 输出 Markdown，后端转 Tiptap JSON 入库。
4. **对话按 Section 隔离**：Message 表存对话历史（计划 1 未建，本计划补）。
5. **summary 异步生成**：确认章节时触发 summary 生成（MVP 同步，失败降级取前 N 字）。

---

## 后端 API 设计（本计划新增）

| 端点 | 方法 | 说明 | 流式 |
|---|---|---|---|
| `/api/v1/sections/{id}/chat` | POST | 引导对话（用户提问→AI 流式回复） | SSE |
| `/api/v1/sections/{id}/generate` | POST | 生成本章草稿（AI 流式输出 Markdown） | SSE |
| `/api/v1/sections/{id}/rewrite` | POST | 段落重写（选中文字→AI 重写） | SSE |
| `/api/v1/sections/{id}/messages` | GET | 获取本章节对话历史 | 否 |

---

## 文件结构（本计划新增）

```
apps/api/app/
├── ai/
│   ├── __init__.py
│   ├── llm_client.py            # LLM 抽象（ChatOpenAI + GLM）
│   ├── section_prompts.py       # 章节 Prompt 注册表（8 种章节策略）
│   ├── context_assembler.py     # 五层上下文装配
│   ├── orchestrator.py          # AI 编排（chat/generate/rewrite）
│   └── markdown_to_tiptap.py    # Markdown → Tiptap JSON 转换
├── models/
│   └── message.py               # 新增：对话消息模型
├── schemas/
│   └── ai.py                    # 新增：chat/generate/rewrite 请求
├── api/
│   └── ai.py                    # 新增：AI 流式 SSE 路由
└── services/
    └── summary_service.py       # 新增：章节 summary 生成
```

---

## 任务 0：Message 模型 + LLM Client

**Files:**
- Create: `apps/api/app/models/message.py`
- Create: `apps/api/app/ai/__init__.py`
- Create: `apps/api/app/ai/llm_client.py`
- Modify: `apps/api/app/models/__init__.py`
- Modify: `apps/api/app/core/config.py`（加 LLM 配置字段）

- [ ] **Step 1: Message 模型**

Create `apps/api/app/models/message.py`:
```python
import uuid

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin


class Message(Base, IdMixin, TimestampMixin):
    __tablename__ = "messages"

    section_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sections.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(20))  # user / assistant
    content: Mapped[str] = mapped_column(Text)
```

更新 `models/__init__.py` 加入 Message。

- [ ] **Step 2: config.py 加 LLM 配置**

在 `Settings` 类加字段:
```python
    # LLM（GLM via OpenAI 兼容协议）
    glm_api_key: str = ""
    glm_base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    glm_model: str = "glm-4-flash"
```

- [ ] **Step 3: LLM Client**

Create `apps/api/app/ai/llm_client.py`:
```python
"""LLM 抽象层。封装 ChatOpenAI 接入 GLM（OpenAI 兼容协议）。"""

from typing import Iterator

from langchain_core.messages import BaseMessage
from langchain_openai import ChatOpenAI

from app.core.config import get_settings


def get_llm(streaming: bool = False) -> ChatOpenAI:
    """构造 LLM 实例。从 settings 读 GLM 配置。"""
    s = get_settings()
    return ChatOpenAI(
        model=s.glm_model,
        base_url=s.glm_base_url,
        api_key=s.glm_api_key,
        streaming=streaming,
        temperature=0.7,
    )


def stream_llm(messages: list[BaseMessage]) -> Iterator[str]:
    """流式调用 LLM，逐 token yield 文本。"""
    llm = get_llm(streaming=True)
    for chunk in llm.stream(messages):
        if chunk.content:
            yield chunk.content
```

- [ ] **Step 4: 迁移 + 测试 + Commit**

```bash
cd apps/api && uv run alembic revision --autogenerate -m "add messages table"
cd apps/api && uv run alembic upgrade head
```

写测试 `tests/test_llm.py`:
```python
def test_get_llm_returns_chat_model():
    from app.ai.llm_client import get_llm
    llm = get_llm()
    assert llm.model_name == "glm-4-flash"


def test_get_llm_streaming_flag():
    from app.ai.llm_client import get_llm
    llm = get_llm(streaming=True)
    assert llm.streaming is True
```

```bash
cd apps/api && uv run pytest tests/test_llm.py -v
git add apps/api/app/models/message.py apps/api/app/ai/ apps/api/app/core/config.py apps/api/app/models/__init__.py apps/api/alembic/versions/ apps/api/tests/test_llm.py apps/api/pyproject.toml apps/api/uv.lock
git commit -m "feat: Message 模型与 LLM Client（ChatOpenAI 接入 GLM-4-Flash）"
```

---

## 任务 1：章节 Prompt 注册表

**Files:**
- Create: `apps/api/app/ai/section_prompts.py`
- Test: `apps/api/tests/test_prompts.py`

- [ ] **Step 1: 实现 Prompt 注册表**

Create `apps/api/app/ai/section_prompts.py`:
```python
"""章节 Prompt 注册表。

每种章节 key 对应一套引导策略：目标、引导问题、输出格式、完成判定。
这是天工的「知识资产」，沉淀专利交底书的专业 know-how。
"""

from dataclasses import dataclass


@dataclass
class SectionPrompt:
    key: str
    goal: str
    guide_questions: list[str]
    output_format: str
    completion_criteria: str


SECTION_PROMPTS: dict[str, SectionPrompt] = {
    "name": SectionPrompt(
        key="name",
        goal="提炼一个清晰、准确的发明名称",
        guide_questions=[
            "这个发明最核心的功能是什么？",
            "它应用在什么领域？",
            "它是一个产品、方法，还是两者结合？",
        ],
        output_format="名称应为：<技术领域>+<核心特征>+<类型>",
        completion_criteria="名称 ≤25字，包含技术领域和核心特征",
    ),
    "field": SectionPrompt(
        key="field",
        goal="明确发明所属的技术领域",
        guide_questions=[
            "这个发明属于哪个技术领域？",
            "它涉及哪些专业技术分类？",
        ],
        output_format="一段简短的技术领域说明",
        completion_criteria="明确指出技术领域和大类",
    ),
    "background": SectionPrompt(
        key="background",
        goal="描述现有技术的现状和不足",
        guide_questions=[
            "目前这个领域有哪些现有技术？",
            "现有技术存在什么问题或不足？",
            "为什么需要改进？",
        ],
        output_format="背景技术应包含：现有技术描述 + 存在的问题",
        completion_criteria="至少描述一种现有技术及其不足",
    ),
    "problem": SectionPrompt(
        key="problem",
        goal="明确发明要解决的技术问题",
        guide_questions=[
            "这个发明针对什么技术问题？",
            "解决这个问题的意义是什么？",
        ],
        output_format="发明目的与技术问题的清晰陈述",
        completion_criteria="明确指出要解决的技术问题",
    ),
    "solution": SectionPrompt(
        key="solution",
        goal="完整描述解决技术问题的技术方案",
        guide_questions=[
            "方案的整体结构/流程是怎样的？",
            "有哪些关键组件/步骤？它们如何配合？",
            "有没有替代实现方式？",
        ],
        output_format="技术方案应包含：整体架构 + 关键要素 + 工作原理",
        completion_criteria="至少覆盖结构、流程、关键要素三个维度",
    ),
    "effect": SectionPrompt(
        key="effect",
        goal="阐述发明带来的有益效果",
        guide_questions=[
            "相比现有技术，这个方案有什么优势？",
            "能带来哪些具体的效果（性能/成本/效率）？",
        ],
        output_format="有益效果应具体、可量化",
        completion_criteria="至少描述一个有益效果并与技术方案对应",
    ),
    "drawings": SectionPrompt(
        key="drawings",
        goal="描述附图内容及图注",
        guide_questions=[
            "有哪些附图？每张图展示什么？",
            "用一两句话描述每张图的内容。",
        ],
        output_format="图N：<图的内容描述>",
        completion_criteria="每张图有对应的图注说明",
    ),
    "embodiment": SectionPrompt(
        key="embodiment",
        goal="详细描述发明的具体实施方式",
        guide_questions=[
            "能否给出一个具体的实施例？",
            "实施例中各部件/步骤的具体参数是什么？",
            "有没有其他变形实施方式？",
        ],
        output_format="具体实施方式应包含至少一个完整实施例",
        completion_criteria="至少一个实施例，与技术方案对应",
    ),
    "custom": SectionPrompt(
        key="custom",
        goal="根据章节标题引导用户撰写内容",
        guide_questions=[
            "这部分您想表达的核心信息是什么？",
            "有没有需要特别强调的关键点或数据？",
            "是否需要配合图示或示例说明？",
        ],
        output_format="结构清晰的段落/列表",
        completion_criteria="内容与标题相关，无空白",
    ),
}


def get_section_prompt(key: str) -> SectionPrompt:
    """获取章节 Prompt 策略。未知 key 返回 custom。"""
    return SECTION_PROMPTS.get(key, SECTION_PROMPTS["custom"])
```

- [ ] **Step 2: 测试**

Create `apps/api/tests/test_prompts.py`:
```python
from app.ai.section_prompts import SECTION_PROMPTS, get_section_prompt


def test_all_standard_keys_exist():
    expected = {"name", "field", "background", "problem", "solution", "effect", "drawings", "embodiment", "custom"}
    assert expected.issubset(SECTION_PROMPTS.keys())


def test_get_section_prompt_known_key():
    sp = get_section_prompt("solution")
    assert sp.key == "solution"
    assert len(sp.guide_questions) > 0


def test_get_section_prompt_unknown_falls_back_to_custom():
    sp = get_section_prompt("nonexistent")
    assert sp.key == "custom"
```

```bash
cd apps/api && uv run pytest tests/test_prompts.py -v
git add apps/api/app/ai/section_prompts.py apps/api/tests/test_prompts.py
git commit -m "feat: 章节 Prompt 注册表（8 种章节引导策略 + custom 兜底）"
```

---

## 任务 2：上下文装配器

**Files:**
- Create: `apps/api/app/ai/context_assembler.py`
- Test: `apps/api/tests/test_context.py`

- [ ] **Step 1: 实现上下文装配**

Create `apps/api/app/ai/context_assembler.py`:
```python
"""五层上下文装配（设计 5.4）。

[系统层] 角色 + 输出规范
[项目层] 已确认章节的 summary
[章节层] 当前章节的 Prompt 策略
[对话层] 本章节历史对话
"""

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.ai.section_prompts import get_section_prompt
from app.models import Message, Section


SYSTEM_PROMPT = """你是「天工」，一个专利交底书撰写助手。你的任务是引导发明人把技术想法整理成规范的专利交底书。

规则：
1. 用专业但通俗的中文交流，避免生硬的法律术语
2. 引导用户补充关键技术细节，不要替用户编造
3. 输出内容用 Markdown 格式（标题用 ##/###，可用列表）
4. 保持客观准确，不夸大技术效果
5. 如果用户的信息不完整，主动追问"""


def assemble_messages(
    section: Section,
    history: list[Message],
    user_input: str | None = None,
    project_summaries: list[dict] | None = None,
) -> list:
    """装配完整的消息列表。

    Args:
        section: 当前章节
        history: 本章节对话历史
        user_input: 用户本次输入（引导对话时传，生成草稿时可不传）
        project_summaries: 已确认章节的 summary 列表 [{title, summary}]
    """
    messages = []

    # [系统层]
    sp = get_section_prompt(section.key)
    system_content = SYSTEM_PROMPT + f"\n\n当前正在撰写章节：【{section.title}】\n"
    system_content += f"本章目标：{sp.goal}\n"
    system_content += f"输出格式要求：{sp.output_format}"

    # [项目层] 已确认章节摘要
    if project_summaries:
        summary_text = "\n".join(
            f"- {s['title']}：{s['summary']}" for s in project_summaries if s.get("summary")
        )
        if summary_text:
            system_content += f"\n\n已完成章节摘要（可作为上下文参考）：\n{summary_text}"

    messages.append(SystemMessage(content=system_content))

    # [对话层] 历史对话
    for msg in history:
        if msg.role == "user":
            messages.append(HumanMessage(content=msg.content))
        else:
            messages.append(AIMessage(content=msg.content))

    # [对话层] 本次输入
    if user_input:
        messages.append(HumanMessage(content=user_input))

    return messages


def get_project_summaries(db, project_id) -> list[dict]:
    """获取项目已确认章节的 summary（用于跨章节上下文）。"""
    from sqlalchemy import select
    from app.models import Section
    sections = db.scalars(
        select(Section).where(
            (Section.project_id == project_id)
            & (Section.status == "confirmed")
            & (Section.summary.isnot(None))
        ).order_by(Section.order)
    )
    return [{"title": s.title, "summary": s.summary} for s in sections]
```

- [ ] **Step 2: 测试 + Commit**

Create `apps/api/tests/test_context.py`:
```python
from app.ai.context_assembler import assemble_messages, SYSTEM_PROMPT
from app.models import Message, Section


def _make_section(key="solution", title="技术方案"):
    return Section(
        template_section_id="ts", order=1, key=key, title=title,
        project_id="00000000-0000-0000-0000-000000000000",
    )


def test_assemble_has_system_prompt():
    section = _make_section()
    msgs = assemble_messages(section, [], user_input="测试")
    assert msgs[0].content.startswith(SYSTEM_PROMPT[:20])


def test_assemble_includes_section_goal():
    section = _make_section("solution")
    msgs = assemble_messages(section, [], user_input="测试")
    assert "技术方案" in msgs[0].content


def test_assemble_includes_history():
    section = _make_section()
    history = [
        Message(section_id="x", role="user", content="之前的问题"),
        Message(section_id="x", role="assistant", content="之前的回答"),
    ]
    msgs = assemble_messages(section, history, user_input="新问题")
    # system + 2 history + 1 new = 4
    assert len(msgs) == 4


def test_assemble_includes_project_summaries():
    section = _make_section()
    summaries = [{"title": "背景技术", "summary": "现有技术不足"}]
    msgs = assemble_messages(section, [], user_input="测试", project_summaries=summaries)
    assert "背景技术" in msgs[0].content
    assert "现有技术不足" in msgs[0].content
```

```bash
cd apps/api && uv run pytest tests/test_context.py -v
git add apps/api/app/ai/context_assembler.py apps/api/tests/test_context.py
git commit -m "feat: 五层上下文装配器（系统/项目/章节/对话层）"
```

---

## 任务 3：Markdown→Tiptap 转换 + AI 编排

**Files:**
- Create: `apps/api/app/ai/markdown_to_tiptap.py`
- Create: `apps/api/app/ai/orchestrator.py`
- Test: `apps/api/tests/test_markdown_tiptap.py`

- [ ] **Step 1: Markdown→Tiptap 转换器**

Create `apps/api/app/ai/markdown_to_tiptap.py`:
```python
"""Markdown → Tiptap JSON 转换器（设计 5.6）。

AI 输出 Markdown，后端转成 Tiptap doc JSON 入库。
支持：段落、标题(##/###)、有序/无序列表、加粗。
"""

import re
from typing import Any


def markdown_to_tiptap(md: str) -> dict[str, Any]:
    """把 Markdown 文本转成 Tiptap doc JSON。"""
    lines = md.strip().split("\n")
    content: list[dict] = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # 标题 ## / ###
        m = re.match(r"^(#{2,3})\s+(.+)$", stripped)
        if m:
            level = len(m.group(1))
            content.append({
                "type": "heading", "attrs": {"level": level},
                "content": _parse_inline(m.group(2)),
            })
            continue

        # 无序列表 - / *
        m = re.match(r"^[-*]\s+(.+)$", stripped)
        if m:
            content.append({
                "type": "bulletList",
                "content": [{
                    "type": "listItem",
                    "content": [{"type": "paragraph", "content": _parse_inline(m.group(1))}],
                }],
            })
            continue

        # 有序列表 1.
        m = re.match(r"^\d+\.\s+(.+)$", stripped)
        if m:
            content.append({
                "type": "orderedList",
                "content": [{
                    "type": "listItem",
                    "content": [{"type": "paragraph", "content": _parse_inline(m.group(1))}],
                }],
            })
            continue

        # 普通段落
        content.append({
            "type": "paragraph", "content": _parse_inline(stripped),
        })

    return {"type": "doc", "content": content or [{"type": "paragraph"}]}


def _parse_inline(text: str) -> list[dict]:
    """解析行内格式（加粗 **text**）。"""
    parts = re.split(r"\*\*(.+?)\*\*", text)
    nodes: list[dict] = []
    for i, part in enumerate(parts):
        if not part:
            continue
        if i % 2 == 1:  # 奇数索引 = 加粗内容
            nodes.append({"type": "text", "text": part, "marks": [{"type": "bold"}]})
        else:
            nodes.append({"type": "text", "text": part})
    return nodes or [{"type": "text", "text": text}]
```

- [ ] **Step 2: AI 编排器**

Create `apps/api/app/ai/orchestrator.py`:
```python
"""AI 编排：引导对话、生成草稿、段落重写。"""

from typing import Iterator

from langchain_core.messages import HumanMessage, SystemMessage

from app.ai.context_assembler import assemble_messages, get_project_summaries
from app.ai.llm_client import stream_llm
from app.ai.section_prompts import get_section_prompt
from app.models import Message, Section


def stream_chat(
    db, section: Section, history: list[Message], user_input: str
) -> Iterator[str]:
    """引导对话：流式回复用户问题。"""
    summaries = get_project_summaries(db, section.project_id)
    messages = assemble_messages(section, history, user_input, summaries)
    yield from stream_llm(messages)


def stream_generate(
    db, section: Section, history: list[Message]
) -> Iterator[str]:
    """生成草稿：基于对话历史生成本章草稿（Markdown 流式输出）。"""
    summaries = get_project_summaries(db, section.project_id)
    sp = get_section_prompt(section.key)
    messages = assemble_messages(section, history, project_summaries=summaries)
    # 追加生成指令
    instruction = (
        f"请根据以上对话内容，整理生成本章节【{section.title}】的草稿。"
        f"要求：{sp.output_format}。用 Markdown 格式输出。"
    )
    messages.append(HumanMessage(content=instruction))
    yield from stream_llm(messages)


def stream_rewrite(
    section: Section, selected_text: str, instruction: str
) -> Iterator[str]:
    """段落重写：基于选中文字 + 指令，流式输出重写结果。"""
    sp = get_section_prompt(section.key)
    system = (
        f"你是专利交底书撰写助手。当前章节：【{section.title}】（{sp.goal}）。"
        f"用户选中了一段文字，请按指令重写。保持 Markdown 格式。"
    )
    messages = [
        SystemMessage(content=system),
        HumanMessage(content=f"原文：\n{selected_text}\n\n指令：{instruction}"),
    ]
    yield from stream_llm(messages)
```

- [ ] **Step 3: 测试 + Commit**

Create `apps/api/tests/test_markdown_tiptap.py`:
```python
from app.ai.markdown_to_tiptap import markdown_to_tiptap


def test_plain_paragraph():
    doc = markdown_to_tiptap("普通段落")
    assert doc["type"] == "doc"
    assert doc["content"][0]["type"] == "paragraph"


def test_heading():
    doc = markdown_to_tiptap("## 标题二")
    assert doc["content"][0]["type"] == "heading"
    assert doc["content"][0]["attrs"]["level"] == 2


def test_bullet_list():
    doc = markdown_to_tiptap("- 列表项")
    assert doc["content"][0]["type"] == "bulletList"


def test_ordered_list():
    doc = markdown_to_tiptap("1. 有序项")
    assert doc["content"][0]["type"] == "orderedList"


def test_bold_text():
    doc = markdown_to_tiptap("**加粗**文字")
    para = doc["content"][0]
    assert any(m.get("type") == "bold" for n in para["content"] for m in n.get("marks", []))


def test_empty_returns_minimal_doc():
    doc = markdown_to_tiptap("")
    assert doc["content"][0]["type"] == "paragraph"
```

```bash
cd apps/api && uv run pytest tests/test_markdown_tiptap.py -v
git add apps/api/app/ai/markdown_to_tiptap.py apps/api/app/ai/orchestrator.py apps/api/tests/test_markdown_tiptap.py
git commit -m "feat: Markdown→Tiptap 转换器与 AI 编排器（chat/generate/rewrite）"
```

---

## 任务 4：流式 SSE API

**Files:**
- Create: `apps/api/app/schemas/ai.py`
- Create: `apps/api/app/api/ai.py`
- Modify: `apps/api/app/api/router.py`
- Modify: `apps/api/app/services/section_service.py`（确认章节时触发 summary）

- [ ] **Step 1: 请求 Schema**

Create `apps/api/app/schemas/ai.py`:
```python
from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str


class GenerateRequest(BaseModel):
    """生成草稿无需参数，对话历史从 DB 取。"""
    pass


class RewriteRequest(BaseModel):
    selected_text: str
    instruction: str = "重写这段内容，使其更清晰规范"
```

- [ ] **Step 2: SSE API 路由**

Create `apps/api/app/api/ai.py`:
```python
"""AI 流式 SSE 路由。"""

import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.orchestrator import stream_chat, stream_generate, stream_rewrite
from app.core.database import get_db
from app.deps import get_current_user
from app.models import Message, Section, User
from app.schemas.ai import ChatRequest, RewriteRequest
from app.services import section_service

router = APIRouter(tags=["ai"])


def _sse_event(event: str, data: dict) -> str:
    """格式化 SSE 事件。"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _get_section_with_history(db: Session, user_id, section_id: str) -> tuple[Section, list[Message]]:
    """获取章节及其对话历史。"""
    section = section_service.get_section(db, user_id=user_id, section_id=section_id)
    history = list(db.scalars(
        select(Message).where(Message.section_id == section.id).order_by(Message.created_at)
    ))
    return section, history


@router.post("/sections/{section_id}/chat")
def chat(
    section_id: str,
    payload: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """引导对话（流式 SSE）。"""
    section, history = _get_section_with_history(db, current_user.id, section_id)

    # 存用户消息
    user_msg = Message(section_id=section.id, role="user", content=payload.message)
    db.add(user_msg)
    db.commit()

    def generate():
        full_response = ""
        try:
            for token in stream_chat(db, section, history, payload.message):
                full_response += token
                yield _sse_event("token", {"text": token})
            # 存 AI 回复
            ai_msg = Message(section_id=section.id, role="assistant", content=full_response)
            db.add(ai_msg)
            db.commit()
            yield _sse_event("done", {"message_id": str(ai_msg.id)})
        except Exception as e:
            yield _sse_event("error", {"code": "llm_error", "message": str(e)[:200]})

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.post("/sections/{section_id}/generate")
def generate_draft(
    section_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """生成本章草稿（流式 SSE，输出 Markdown）。"""
    section, history = _get_section_with_history(db, current_user.id, section_id)

    def generate():
        full_md = ""
        try:
            for token in stream_generate(db, section, history):
                full_md += token
                yield _sse_event("token", {"text": token})
            # 转 Tiptap 存入章节
            from app.ai.markdown_to_tiptap import markdown_to_tiptap
            section.content = markdown_to_tiptap(full_md)
            if section.status == "empty":
                section.status = "drafting"
            db.commit()
            yield _sse_event("done", {"section_id": str(section.id)})
        except Exception as e:
            yield _sse_event("error", {"code": "llm_error", "message": str(e)[:200]})

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.post("/sections/{section_id}/rewrite")
def rewrite(
    section_id: str,
    payload: RewriteRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """段落重写（流式 SSE）。"""
    section = section_service.get_section(db, user_id=current_user.id, section_id=section_id)

    def generate():
        try:
            for token in stream_rewrite(section, payload.selected_text, payload.instruction):
                yield _sse_event("token", {"text": token})
            yield _sse_event("done", {})
        except Exception as e:
            yield _sse_event("error", {"code": "llm_error", "message": str(e)[:200]})

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.get("/sections/{section_id}/messages")
def list_messages(
    section_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取章节对话历史。"""
    section = section_service.get_section(db, user_id=current_user.id, section_id=section_id)
    messages = list(db.scalars(
        select(Message).where(Message.section_id == section.id).order_by(Message.created_at)
    ))
    return [
        {"id": str(m.id), "role": m.role, "content": m.content, "created_at": m.created_at.isoformat()}
        for m in messages
    ]
```

- [ ] **Step 3: 注册路由**

Modify `apps/api/app/api/router.py` 加 `from app.api import ai` 和 `api_router.include_router(ai.router)`。

- [ ] **Step 4: Commit**

```bash
git add apps/api/app/schemas/ai.py apps/api/app/api/ai.py apps/api/app/api/router.py
git commit -m "feat: AI 流式 SSE API（引导对话/生成草稿/段落重写/历史）"
```

---

## 任务 5：跨章节 summary

**Files:**
- Create: `apps/api/app/services/summary_service.py`
- Modify: `apps/api/app/services/section_service.py`（确认时触发 summary）

- [ ] **Step 1: summary 服务**

Create `apps/api/app/services/summary_service.py`:
```python
"""章节 summary 生成（设计 5.10）。

确认章节时触发，生成 100-200 字摘要供跨章节上下文用。
失败降级为取正文前 N 字。
"""

from sqlalchemy.orm import Session

from app.ai.llm_client import get_llm
from app.models import Section


def generate_summary(db: Session, section: Section) -> str:
    """为章节生成 summary。失败降级取前 200 字。"""
    if not section.content:
        return ""

    # 从 Tiptap JSON 提取纯文本
    text = _extract_text(section.content)
    if not text.strip():
        return ""

    try:
        from langchain_core.messages import HumanMessage
        llm = get_llm()
        resp = llm.invoke([
            HumanMessage(content=(
                f"请用 100-200 字概括以下专利交底书章节内容的核心要点：\n\n"
                f"章节：{section.title}\n内容：{text[:2000]}"
            ))
        ])
        summary = resp.content.strip()
        section.summary = summary[:500]
        db.commit()
        return summary
    except Exception:
        # 降级：取前 200 字
        fallback = text[:200]
        section.summary = fallback
        db.commit()
        return fallback


def _extract_text(tiptap_doc: dict) -> str:
    """从 Tiptap JSON 提取纯文本。"""
    parts: list[str] = []

    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "text":
                parts.append(node.get("text", ""))
            for child in node.get("content", []):
                walk(child)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(tiptap_doc)
    return "".join(parts)
```

- [ ] **Step 2: section_service 确认时触发 summary**

在 `section_service.update_section` 里，当 status 变为 confirmed 时触发 summary:
```python
    if status is not None:
        if status not in ("empty", "drafting", "confirmed"):
            raise ValidationError("无效的章节状态")
        old_status = section.status
        section.status = status
        if status == "confirmed" and old_status != "confirmed":
            # 触发 summary 生成（异步，MVP 同步）
            from app.services.summary_service import generate_summary
            generate_summary(db, section)
```

- [ ] **Step 3: 测试 + Commit**

```bash
cd apps/api && uv run pytest tests/ -v
git add apps/api/app/services/summary_service.py apps/api/app/services/section_service.py
git commit -m "feat: 跨章节 summary 生成（确认时触发，失败降级取前 N 字）"
```

---

## 任务 6：前端 AI 对话面板

**Files:**
- Create: `apps/web/src/components/ai-chat-panel.tsx`
- Modify: `apps/web/src/app/(app)/projects/[id]/page.tsx`（加 AI 面板）
- Modify: `apps/web/src/lib/api.ts`（加 SSE 流式调用）

- [ ] **Step 1: API 层加 SSE 调用**

在 `apps/web/src/lib/api.ts` 追加:
```typescript
  // ── AI（SSE 流式）──
  streamChat: async (sectionId: string, message: string, onToken: (t: string) => void) => {
    const res = await fetch(`${BASE}/api/v1/sections/${sectionId}/chat`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message }),
    })
    return _consumeSSE(res, onToken)
  },

  streamGenerate: async (sectionId: string, onToken: (t: string) => void) => {
    const res = await fetch(`${BASE}/api/v1/sections/${sectionId}/generate`, {
      method: 'POST',
      credentials: 'include',
    })
    return _consumeSSE(res, onToken)
  },
```

在 api.ts 加 SSE 解析辅助函数:
```typescript
async function _consumeSSE(res: Response, onToken: (t: string) => void): Promise<void> {
  if (!res.body) return
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() || ''
    for (const line of lines) {
      if (line.startsWith('data: ')) {
        try {
          const data = JSON.parse(line.slice(6))
          if (data.text) onToken(data.text)
        } catch {}
      }
    }
  }
}
```

- [ ] **Step 2: AI 对话面板组件**

Create `apps/web/src/components/ai-chat-panel.tsx`:
```tsx
'use client'

import { useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { api } from '@/lib/api'

interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}

interface AIChatPanelProps {
  sectionId: string
}

export function AIChatPanel({ sectionId }: AIChatPanelProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [generating, setGenerating] = useState(false)

  async function handleSend() {
    if (!input.trim() || loading) return
    const userMsg: ChatMessage = { role: 'user', content: input }
    setMessages((m) => [...m, userMsg, { role: 'assistant', content: '' }])
    setInput('')
    setLoading(true)

    let aiText = ''
    try {
      await api.streamChat(sectionId, userMsg.content, (token) => {
        aiText += token
        setMessages((m) => {
          const copy = [...m]
          copy[copy.length - 1] = { role: 'assistant', content: aiText }
          return copy
        })
      })
    } catch {
      toast.error('AI 回复失败')
    } finally {
      setLoading(false)
    }
  }

  async function handleGenerate() {
    setGenerating(true)
    toast.info('正在生成草稿...')
    try {
      let md = ''
      await api.streamGenerate(sectionId, (token) => { md += token })
      toast.success('草稿已生成并填入编辑器')
      // 刷新页面让编辑器加载新内容
      setTimeout(() => window.location.reload(), 500)
    } catch {
      toast.error('生成失败')
    } finally {
      setGenerating(false)
    }
  }

  return (
    <div className="flex h-full flex-col border-l pl-4" style={{ width: 320 }}>
      <div className="flex items-center justify-between pb-2">
        <h3 className="text-sm font-semibold">AI 助手</h3>
        <Button size="sm" variant="outline" onClick={handleGenerate} disabled={generating}>
          {generating ? '生成中...' : '生成草稿'}
        </Button>
      </div>

      <div className="flex-1 space-y-3 overflow-y-auto py-2">
        {messages.length === 0 && (
          <p className="text-sm text-muted-foreground">向 AI 描述你的想法，或直接点「生成草稿」</p>
        )}
        {messages.map((m, i) => (
          <div key={i} className={m.role === 'user' ? 'text-right' : ''}>
            <div className={`inline-block max-w-[90%] rounded-lg px-3 py-2 text-sm ${
              m.role === 'user' ? 'bg-primary text-primary-foreground' : 'bg-muted'
            }`}>
              {m.content || '...'}
            </div>
          </div>
        ))}
      </div>

      <div className="flex gap-2 pt-2">
        <Input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && (e.preventDefault(), handleSend())}
          placeholder="问 AI..."
          disabled={loading}
        />
        <Button size="sm" onClick={handleSend} disabled={loading || !input.trim()}>
          发送
        </Button>
      </div>
    </div>
  )
}
```

- [ ] **Step 3: 项目详情页加 AI 面板**

修改 `apps/web/src/app/(app)/projects/[id]/page.tsx`，在编辑器右侧加 AI 面板。把布局从两栏改三栏：
```tsx
import { AIChatPanel } from '@/components/ai-chat-panel'

// 在 return 里改为三栏布局
<div className="grid grid-cols-[200px_1fr_320px] gap-4">
  <aside>大纲</aside>
  <div>编辑器</div>
  {current && <AIChatPanel sectionId={current.id} />}
</div>
```

- [ ] **Step 4: 构建验证 + Commit**

```bash
cd apps/web && pnpm build
git add apps/web/src/
git commit -m "feat: 前端 AI 对话面板（流式渲染 + 生成草稿按钮）"
```

---

## 任务 7：端到端验证（真实 GLM）

- [ ] **Step 1: 启动后端 + 前端**

```bash
cd apps/api && uv run uvicorn app.main:app --reload
cd apps/web && pnpm dev
```

- [ ] **Step 2: 浏览器验证 AI 撰写**

1. 登录 → 新建项目 → 进入项目详情
2. 选中「技术方案」章节 → 在 AI 面板输入"我想做一个基于 AI 的智能温控系统"→ 发送
3. AI 流式回复（引导提问）
4. 继续对话补充细节
5. 点「生成草稿」→ AI 流式生成 Markdown → 自动转 Tiptap 填入编辑器
6. 切换到下一章节 → 确认 → 验证 summary 生成
7. 回到第一章 → AI 应能引用已确认章节的 summary（跨章节上下文）

- [ ] **Step 3: Commit**

```bash
git commit --allow-empty -m "chore: 计划 4 AI 撰写引擎端到端验证通过（真实 GLM-4-Flash）"
```

---

## 完成标准

- [ ] Message 模型 + LLM Client（ChatOpenAI + GLM）
- [ ] 章节 Prompt 注册表（8 种 + custom）
- [ ] 五层上下文装配器
- [ ] Markdown→Tiptap 转换器
- [ ] AI 编排（chat/generate/rewrite）
- [ ] 流式 SSE API
- [ ] 跨章节 summary（确认时触发）
- [ ] 前端 AI 对话面板（流式渲染 + 生成草稿）
- [ ] 真实 GLM 端到端验证通过
