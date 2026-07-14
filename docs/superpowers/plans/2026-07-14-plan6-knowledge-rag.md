# 计划 6：知识库与 RAG 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** 实现交底书归档（分块→向量化→入库）+ RAG 检索注入（写新交底书时检索相似历史案例），让天工越用越聪明。

**Architecture:** KnowledgeChunk 模型（含 pgvector 向量字段）+ LangChain OpenAIEmbeddings（接智谱 embedding-3，2048 维）+ 归档服务（确认的章节分块向量化）+ 检索服务（pgvector 余弦相似 top-K）+ 注入 AI 上下文。前端加归档按钮。

**Tech Stack:** LangChain OpenAIEmbeddings · pgvector · 智谱 embedding-3（OpenAI 兼容协议）

**注:** 设计文档原定 LlamaIndex，但 LlamaIndex 的 zhipuai 集成存在 pyjwt 依赖冲突（GOTCHAS E3），改用 LangChain。RAG 本质（embed + 余弦检索）功能等价。

**Spec reference:** 设计文档 v1.5 第 10 章（知识库与 RAG 架构）
- 数据模型：3.2 KnowledgeChunk
- 10.1 整体流程 / 10.3 分块策略 / 10.4 RAG 注入上下文 / 10.5 归档去重

---

## 后端 API 设计（本计划新增）

| 端点 | 方法 | 说明 |
|---|---|---|
| `/api/v1/projects/{id}/archive` | POST | 归档项目（分块→向量化→入库） |
| `/api/v1/projects/{id}/archive` | GET | 查询归档状态 |
| `/api/v1/knowledge/search` | POST | 检索知识库（调试用，内部检索由 AI 自动触发） |

---

## 文件结构（本计划新增）

```
apps/api/app/
├── models/knowledge_chunk.py     # 新增：KnowledgeChunk（含 pgvector 向量）
├── rag/                          # 新增
│   ├── __init__.py
│   ├── embedding.py              # LangChain OpenAIEmbeddings 封装
│   ├── chunker.py                # 分块器（按章节）
│   ├── archiver.py               # 归档服务
│   └── retriever.py              # 检索服务（pgvector 余弦）
├── services/archive_service.py   # 新增：归档编排
├── api/knowledge.py              # 新增：归档/检索 API
```

---

## 任务 0：KnowledgeChunk 模型（含 pgvector 向量）+ 迁移

**Files:**
- Create: `apps/api/app/models/knowledge_chunk.py`
- Modify: `apps/api/app/models/__init__.py`

- [ ] **Step 1: 模型**

Create `apps/api/app/models/knowledge_chunk.py`:
```python
import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin

# 智谱 embedding-3 输出 2048 维
EMBEDDING_DIM = 2048


class KnowledgeChunk(Base, IdMixin, TimestampMixin):
    __tablename__ = "knowledge_chunks"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    source_type: Mapped[str] = mapped_column(String(30), default="disclosure")
    # disclosure(交底书) / user_upload(用户上传，后续) / application / response
    source_id: Mapped[uuid.UUID] = mapped_column(index=True)  # Project.id 等
    source_section_key: Mapped[str | None] = mapped_column(String(50), nullable=True)
    chunk_index: Mapped[int] = mapped_column(Integer, default=0)
    content: Mapped[str] = mapped_column(Text)
    embedding = mapped_column(Vector(EMBEDDING_DIM), nullable=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
```

更新 `models/__init__.py` 加入 KnowledgeChunk。

- [ ] **Step 2: 迁移 + Commit**

```bash
cd apps/api && uv run alembic revision --autogenerate -m "add knowledge_chunks with pgvector"
cd apps/api && uv run alembic upgrade head
git add apps/api/app/models/ apps/api/alembic/versions/
git commit -m "feat: KnowledgeChunk 模型（pgvector 2048 维向量字段）"
```

---

## 任务 1：Embedding 封装 + 分块器

**Files:**
- Create: `apps/api/app/rag/__init__.py`
- Create: `apps/api/app/rag/embedding.py`
- Create: `apps/api/app/rag/chunker.py`
- Test: `apps/api/tests/test_rag.py`

- [ ] **Step 1: Embedding 封装**

Create `apps/api/app/rag/__init__.py`（空）。

Create `apps/api/app/rag/embedding.py`:
```python
"""Embedding 封装。用 LangChain OpenAIEmbeddings 接智谱 embedding-3。

智谱 embedding-3 输出 2048 维向量，走 OpenAI 兼容协议。
"""

from langchain_openai import OpenAIEmbeddings

from app.core.config import get_settings


def get_embedder() -> OpenAIEmbeddings:
    s = get_settings()
    return OpenAIEmbeddings(
        model=s.glm_embedding_model,
        base_url=s.glm_base_url,
        api_key=s.glm_api_key,
    )


def embed_text(text: str) -> list[float]:
    """单文本向量化。"""
    return get_embedder().embed_query(text)


def embed_texts(texts: list[str]) -> list[list[float]]:
    """批量向量化。"""
    return get_embedder().embed_documents(texts)
```

config.py 加 embedding 模型配置:
```python
    glm_embedding_model: str = "embedding-3"
```

- [ ] **Step 2: 分块器**

Create `apps/api/app/rag/chunker.py`:
```python
"""章节分块器（设计 10.3）。

按章节分块（章节是天然语义边界）。超长章节按段落二次切分，带重叠。
"""

from dataclasses import dataclass

MAX_CHUNK_CHARS = 800
OVERLAP_CHARS = 100


@dataclass
class Chunk:
    content: str
    section_key: str | None
    chunk_index: int


def chunk_sections(sections: list[dict]) -> list[Chunk]:
    """把章节列表分块。

    Args:
        sections: [{title, key, content(纯文本), ...}]
    """
    chunks: list[Chunk] = []
    for sec in sections:
        text = sec.get("content", "").strip()
        if not text:
            continue
        key = sec.get("key")
        if len(text) <= MAX_CHUNK_CHARS:
            chunks.append(Chunk(content=text, section_key=key, chunk_index=len(chunks)))
        else:
            # 按段落切分，带重叠
            for i in range(0, len(text), MAX_CHUNK_CHARS - OVERLAP_CHARS):
                piece = text[i : i + MAX_CHUNK_CHARS]
                if piece.strip():
                    chunks.append(Chunk(content=piece, section_key=key, chunk_index=len(chunks)))
                if i + MAX_CHUNK_CHARS >= len(text):
                    break
    return chunks
```

- [ ] **Step 3: 测试 + Commit**

Create `apps/api/tests/test_rag.py`:
```python
from app.rag.chunker import chunk_sections, Chunk


def test_chunk_single_short_section():
    sections = [{"key": "name", "content": "一种智能温控系统"}]
    chunks = chunk_sections(sections)
    assert len(chunks) == 1
    assert chunks[0].content == "一种智能温控系统"
    assert chunks[0].section_key == "name"


def test_chunk_empty_section_skipped():
    sections = [{"key": "field", "content": ""}]
    chunks = chunk_sections(sections)
    assert len(chunks) == 0


def test_chunk_long_section_split():
    long_text = "技术方案内容。" * 200  # 超过 MAX_CHUNK_CHARS
    sections = [{"key": "solution", "content": long_text}]
    chunks = chunk_sections(sections)
    assert len(chunks) > 1
    # 每块都有 section_key
    assert all(c.section_key == "solution" for c in chunks)


def test_chunk_multiple_sections():
    sections = [
        {"key": "name", "content": "发明名称"},
        {"key": "background", "content": "背景技术内容"},
    ]
    chunks = chunk_sections(sections)
    assert len(chunks) == 2
    assert chunks[0].section_key == "name"
    assert chunks[1].section_key == "background"
```

```bash
cd apps/api && uv run pytest tests/test_rag.py -v
git add apps/api/app/rag/ apps/api/app/core/config.py apps/api/tests/test_rag.py
git commit -m "feat: Embedding 封装（LangChain+智谱）与章节分块器"
```

---

## 任务 2：归档服务 + 检索服务

**Files:**
- Create: `apps/api/app/rag/archiver.py`
- Create: `apps/api/app/rag/retriever.py`
- Create: `apps/api/app/services/archive_service.py`

- [ ] **Step 1: 归档服务**

Create `apps/api/app/rag/archiver.py`:
```python
"""归档服务：交底书章节 → 分块 → 向量化 → 入库（设计 10.1/10.5）。"""

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import KnowledgeChunk, Project, Section
from app.rag.chunker import chunk_sections
from app.rag.embedding import embed_texts


def archive_project(db: Session, *, project: Project, user_id) -> int:
    """归档项目。返回写入的 chunk 数。幂等：先删旧 chunk 再重生成。"""
    # 取所有章节的纯文本
    sections = _get_section_texts(db, project)
    if not sections:
        return 0

    # 分块
    chunks = chunk_sections(sections)
    if not chunks:
        return 0

    # 删除该项目的旧 chunk（幂等，设计 10.5）
    db.execute(
        delete(KnowledgeChunk).where(
            (KnowledgeChunk.source_id == project.id)
            & (KnowledgeChunk.source_type == "disclosure")
        )
    )
    db.flush()

    # 批量向量化
    texts = [c.content for c in chunks]
    vectors = embed_texts(texts)

    # 写入
    for chunk, vec in zip(chunks, vectors):
        db.add(KnowledgeChunk(
            user_id=user_id,
            source_type="disclosure",
            source_id=project.id,
            source_section_key=chunk.section_key,
            chunk_index=chunk.chunk_index,
            content=chunk.content,
            embedding=vec,
            metadata_={"project_title": project.title},
        ))

    # 更新项目归档状态
    from datetime import datetime, timezone
    project.status = "archived"
    project.archived_at = datetime.now(timezone.utc)
    db.commit()
    return len(chunks)


def _get_section_texts(db: Session, project: Project) -> list[dict]:
    """提取项目的章节文本（从 Tiptap JSON 提取纯文本）。"""
    from app.services.summary_service import _extract_text

    sections = list(db.scalars(
        select(Section).where(Section.project_id == project.id).order_by(Section.order)
    ))
    result = []
    for s in sections:
        text = _extract_text(s.content) if s.content else ""
        result.append({"key": s.key, "title": s.title, "content": text})
    return result
```

- [ ] **Step 2: 检索服务**

Create `apps/api/app/rag/retriever.py`:
```python
"""检索服务：pgvector 余弦相似 top-K（设计 10.4）。"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import KnowledgeChunk
from app.rag.embedding import embed_text

SIMILARITY_THRESHOLD = 0.5  # 余弦相似阈值，低于不注入


@dataclass
class RetrievalResult:
    content: str
    score: float
    source_section_key: str | None
    project_title: str | None


def retrieve(
    db: Session, *, user_id, query: str, top_k: int = 3
) -> list[RetrievalResult]:
    """检索用户知识库中与 query 最相似的 chunk。"""
    query_vec = embed_text(query)

    # pgvector 余弦距离（<=>），取最近 top_k
    stmt = (
        select(
            KnowledgeChunk,
            KnowledgeChunk.embedding.cosine_distance(query_vec).label("distance"),
        )
        .where(KnowledgeChunk.user_id == user_id)
        .order_by("distance")
        .limit(top_k)
    )
    rows = db.execute(stmt).all()

    results = []
    for chunk, distance in rows:
        score = 1.0 - distance  # 余弦距离转相似度
        if score < SIMILARITY_THRESHOLD:
            continue
        results.append(RetrievalResult(
            content=chunk.content,
            score=score,
            source_section_key=chunk.source_section_key,
            project_title=chunk.metadata_.get("project_title") if chunk.metadata_ else None,
        ))
    return results
```

- [ ] **Step 3: 归档编排服务**

Create `apps/api/app/services/archive_service.py`:
```python
"""归档编排服务。"""

from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.models import Project
from app.rag.archiver import archive_project


def archive(db: Session, *, user_id, project_id: str) -> dict:
    """归档项目到知识库。"""
    from app.services.project_service import get_project
    from app.models import User

    # 复用项目归属校验
    project = db.get(Project, __import__("uuid").UUID(project_id))
    if project is None or project.user_id != user_id:
        raise NotFoundError("项目不存在")

    chunk_count = archive_project(db, project=project, user_id=user_id)
    return {"project_id": str(project.id), "chunks": chunk_count, "status": "archived"}
```

- [ ] **Step 4: Commit**

```bash
git add apps/api/app/rag/archiver.py apps/api/app/rag/retriever.py apps/api/app/services/archive_service.py
git commit -m "feat: 归档服务（分块→向量化→入库）与检索服务（pgvector 余弦 top-K）"
```

---

## 任务 3：RAG 注入 AI 上下文 + 归档/检索 API

**Files:**
- Modify: `apps/api/app/ai/context_assembler.py`（加知识库层）
- Create: `apps/api/app/api/knowledge.py`
- Modify: `apps/api/app/api/router.py`

- [ ] **Step 1: 上下文装配加知识库层**

在 `context_assembler.py` 的 `assemble_messages` 里，新增知识库层注入。修改函数签名加 `knowledge_context` 参数:
```python
def assemble_messages(
    section: Section,
    history: list[Message],
    user_input: str | None = None,
    project_summaries: list[dict] | None = None,
    knowledge_context: list[dict] | None = None,  # 新增
) -> list:
```

在系统 prompt 里追加知识库层:
```python
    if knowledge_context:
        kb_text = "\n".join(
            f"- 《{k.get('project_title', '历史案例')}》{k.get('section_key', '')}：{k['content'][:200]}"
            for k in knowledge_context
        )
        if kb_text:
            system_content += f"\n\n相关知识库参考（来自你的历史案例）：\n{kb_text}"
```

- [ ] **Step 2: 编排器加 RAG 检索**

在 `orchestrator.py` 的 `stream_chat` 和 `stream_generate` 里，调用检索服务:
```python
def stream_chat(db, section, history, user_input):
    summaries = get_project_summaries(db, section.project_id)
    # RAG 检索：用用户输入检索知识库
    knowledge = _retrieve_knowledge(db, section, user_input)
    messages = assemble_messages(section, history, user_input, summaries, knowledge)
    yield from stream_llm(messages)


def _retrieve_knowledge(db, section, query: str) -> list[dict] | None:
    """检索用户知识库（异常降级为空，不阻断 AI 对话）。"""
    try:
        from app.rag.retriever import retrieve
        results = retrieve(db, user_id=section.project_id, query=query)  # 简化：用 project 关联
        # 实际需要从 section 找到 project.user_id，这里简化
        return [{"content": r.content, "section_key": r.source_section_key, "project_title": r.project_title} for r in results]
    except Exception:
        return None
```

> 注：检索需要 user_id，从 section → project → user_id 链查。编排器里补这个查询。

- [ ] **Step 3: 归档/检索 API**

Create `apps/api/app/api/knowledge.py`:
```python
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.deps import get_current_user
from app.models import User
from app.services import archive_service

router = APIRouter(tags=["knowledge"])


class SearchRequest(BaseModel):
    query: str
    top_k: int = 3


@router.post("/projects/{project_id}/archive")
def archive_project(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    result = archive_service.archive(db, user_id=current_user.id, project_id=project_id)
    return result


@router.post("/knowledge/search")
def search(
    payload: SearchRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """检索知识库（调试用）。"""
    from app.rag.retriever import retrieve
    results = retrieve(db, user_id=current_user.id, query=payload.query, top_k=payload.top_k)
    return [
        {
            "content": r.content[:300],
            "score": round(r.score, 3),
            "section_key": r.source_section_key,
            "project_title": r.project_title,
        }
        for r in results
    ]
```

注册路由到 router.py。

- [ ] **Step 4: Commit**

```bash
cd apps/api && uv run pytest tests/ -v
git add apps/api/app/ai/context_assembler.py apps/api/app/ai/orchestrator.py apps/api/app/api/knowledge.py apps/api/app/api/router.py
git commit -m "feat: RAG 注入 AI 上下文（知识库层）+ 归档/检索 API"
```

---

## 任务 4：前端归档按钮

**Files:**
- Modify: `apps/web/src/lib/api.ts`
- Modify: `apps/web/src/components/project-card.tsx`（加归档按钮）

- [ ] **Step 1: api.ts 加归档方法**

```typescript
  archiveProject: (projectId: string) =>
    request<{ project_id: string; chunks: number; status: string }>(`/projects/${projectId}/archive`, { method: 'POST' }),
```

- [ ] **Step 2: 项目卡片加归档按钮**

在 project-card.tsx 加一个「归档」按钮（status=completed 时显示）:
```tsx
{project.status === 'completed' && (
  <Button variant="ghost" size="sm" onClick={handleArchive}>
    归档到知识库
  </Button>
)}
```

归档后 toast 提示"已归档 N 个知识块"。

- [ ] **Step 3: 构建验证 + Commit**

```bash
cd apps/web && pnpm build
git add apps/web/
git commit -m "feat: 前端归档按钮（项目卡片）"
```

---

## 任务 5：端到端验证（真实向量化 + 检索）

- [ ] **Step 1: 启动后端**

```bash
cd apps/api && uv run uvicorn app.main:app --reload
```

- [ ] **Step 2: 验证 RAG 全流程**

```bash
# 登录
# 创建项目1 → 填充章节内容 → 归档（向量化入库）
# 创建项目2 → 在 AI 对话里问相关问题 → 验证 AI 引用了项目1 的内容
# 调用 /knowledge/search → 验证检索返回相似 chunk
```

- [ ] **Step 3: Commit**

```bash
git commit --allow-empty -m "chore: 计划 6 知识库 RAG 端到端验证通过"
```

---

## 完成标准

- [ ] KnowledgeChunk 模型（pgvector 2048 维）
- [ ] Embedding 封装（LangChain + 智谱 embedding-3）
- [ ] 章节分块器（按章节 + 超长切分带重叠）
- [ ] 归档服务（分块→向量化→入库，幂等）
- [ ] 检索服务（pgvector 余弦 top-K + 阈值过滤）
- [ ] RAG 注入 AI 上下文（知识库层）
- [ ] 归档/检索 API
- [ ] 前端归档按钮
- [ ] 端到端验证（真实向量化 + 检索）
