# 计划 7：审查引擎与 Rubric 自定义 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** 实现确定性审查评估管线（Rubric 驱动 + 自一致性 + 跨会话记忆），根治"跨对话评分不稳定"问题，并支持用户自定义 Rubric。

**Architecture:** ReviewRubric 模型（系统默认 + 用户覆盖）+ ReviewRecord 模型（审查记录，支撑跨会话记忆）+ ReviewGraph 确定性评估管线（load→score→aggregate→persist）+ Rubric 驱动的结构化评分 + 自一致性（关键维度多次取均值）。前端审查报告页 + Rubric 配置页。

**注:** 不引入 LangGraph 状态机（MVP 用确定性管线 + DB 持久化实现同等效果：Rubric 持久化 = 根治漂移，ReviewRecord = 跨会话记忆，多次评分取均值 = 自一致性）。LangGraph Checkpoint/Store 留到后续需要复杂状态恢复时引入。

**Tech Stack:** GLM-4-Flash（结构化评分）· FastAPI · React

**Spec reference:** 设计文档 v1.5 第 6 章（审查与评分引擎）+ 第 7 章（自定义能力）
- 6.2 三层稳定性方案 / 6.3 ReviewGraph / 6.4 Rubric 结构 / 6.5 审查报告 / 6.7 记忆语义
- 7.2 Rubric 自定义（覆盖式）
- 验收：同交底书+Rubric 新对话审查标准差 ≤ 3 分

---

## 关键设计：三层稳定性如何实现

| 层 | 机制 | 实现 |
|---|---|---|
| ① Rubric 持久化 | 评分标准结构化存库，每次审查强制注入 | ReviewRubric 表 + score 节点读 Rubric 注入 prompt |
| ② 自一致性 | 关键维度多次评分取均值 | score 节点对每维度跑 N=2 次，取均值 |
| ③ 跨会话记忆 | 记住上次审查记录 | ReviewRecord 表 + load 节点加载上次分数/未解决问题 |

---

## 后端 API 设计

| 端点 | 方法 | 说明 |
|---|---|---|
| `/api/v1/projects/{id}/review` | POST | 执行审查（流式或同步返回报告） |
| `/api/v1/projects/{id}/reviews` | GET | 审查历史列表 |
| `/api/v1/rubric` | GET | 获取当前生效 Rubric |
| `/api/v1/rubric` | PUT | 更新 Rubric（覆盖式） |
| `/api/v1/rubric/reset` | POST | 恢复系统默认 Rubric |

---

## 文件结构（本计划新增）

```
apps/api/app/
├── models/review_rubric.py       # 新增
├── models/review_record.py       # 新增
├── schemas/review.py             # 新增
├── services/review_service.py    # 新增：审查编排（确定性管线）
├── services/rubric_service.py    # 新增：Rubric 管理
├── ai/rubric_prompts.py          # 新增：Rubric 驱动的评分 prompt
├── api/review.py                 # 新增
apps/web/src/
├── components/review-report.tsx  # 新增：审查报告展示
├── components/rubric-editor.tsx  # 新增：Rubric 配置
├── app/(app)/projects/[id]/review/page.tsx  # 新增：审查页
```

---

## 任务 0：ReviewRubric + ReviewRecord 模型 + 默认 Rubric 种子

**Files:**
- Create: `apps/api/app/models/review_rubric.py`
- Create: `apps/api/app/models/review_record.py`
- Modify: `apps/api/app/models/__init__.py`

- [ ] **Step 1: ReviewRubric 模型**

Create `apps/api/app/models/review_rubric.py`:
```python
import uuid

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, JSONType, TimestampMixin


class ReviewRubric(Base, IdMixin, TimestampMixin):
    __tablename__ = "review_rubrics"

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    scope: Mapped[str] = mapped_column(String(20))  # system / user
    name: Mapped[str] = mapped_column(String(100))
    criteria: Mapped[list] = mapped_column(JSONType)  # 维度定义数组
    is_customized: Mapped[bool] = mapped_column(Boolean, default=False)
```

- [ ] **Step 2: ReviewRecord 模型**

Create `apps/api/app/models/review_record.py`:
```python
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, JSONType, TimestampMixin


class ReviewRecord(Base, IdMixin, TimestampMixin):
    __tablename__ = "review_records"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    rubric_snapshot: Mapped[list] = mapped_column(JSONType)  # 本次所用 Rubric 快照
    round: Mapped[int] = mapped_column(Integer, default=1)
    total_score: Mapped[int] = mapped_column(Integer, default=0)
    previous_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dimension_scores: Mapped[list] = mapped_column(JSONType)
    resolved_issues: Mapped[list] = mapped_column(JSONType, default=list)
    remaining_issues: Mapped[list] = mapped_column(JSONType, default=list)
```

- [ ] **Step 3: 默认 Rubric 定义**

在 `seed_service.py` 加默认 Rubric 种子函数:
```python
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
    from app.models import ReviewRubric
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
```

- [ ] **Step 4: 迁移 + Commit**

更新 `models/__init__.py`，生成迁移。

```bash
cd apps/api && uv run alembic revision --autogenerate -m "add review_rubrics review_records"
cd apps/api && uv run alembic upgrade head
cd apps/api && uv run python -m scripts.seed_default_template  # 顺便确保模板
git add apps/api/app/models/ apps/api/app/services/seed_service.py apps/api/alembic/versions/
git commit -m "feat: ReviewRubric/ReviewRecord 模型 + 默认 Rubric 种子"
```

---

## 任务 1：Rubric 服务 + API

**Files:**
- Create: `apps/api/app/schemas/review.py`
- Create: `apps/api/app/services/rubric_service.py`
- Create: `apps/api/app/api/review.py`（Rubric 部分）

- [ ] **Step 1: Schema**

Create `apps/api/app/schemas/review.py`:
```python
from datetime import datetime

from pydantic import BaseModel


class RubricCriterion(BaseModel):
    key: str
    name: str
    weight: float
    scoring_guide: dict[str, str]


class RubricOut(BaseModel):
    id: str
    scope: str
    name: str
    criteria: list[dict]
    is_customized: bool

    model_config = {"from_attributes": True}


class RubricUpdate(BaseModel):
    name: str | None = None
    criteria: list[dict] | None = None


class ReviewRecordOut(BaseModel):
    id: str
    round: int
    total_score: int
    previous_score: int | None
    dimension_scores: list[dict]
    resolved_issues: list
    remaining_issues: list
    created_at: datetime

    model_config = {"from_attributes": True}
```

- [ ] **Step 2: Rubric 服务**

Create `apps/api/app/services/rubric_service.py`:
```python
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ReviewRubric


def get_effective_rubric(db: Session, *, user_id) -> ReviewRubric:
    """获取生效的 Rubric：用户自定义 > 系统默认。"""
    user_rubric = db.scalar(
        select(ReviewRubric).where(ReviewRubric.user_id == user_id)
    )
    if user_rubric:
        return user_rubric
    system_rubric = db.scalar(select(ReviewRubric).where(ReviewRubric.scope == "system"))
    return system_rubric


def update_user_rubric(db: Session, *, user_id, criteria: list[dict], name: str | None = None) -> ReviewRubric:
    """更新用户 Rubric（覆盖式）。"""
    existing = db.scalar(
        select(ReviewRubric).where(ReviewRubric.user_id == user_id)
    )
    if existing:
        existing.criteria = criteria
        if name:
            existing.name = name
        existing.is_customized = True
        db.commit()
        db.refresh(existing)
        return existing
    rubric = ReviewRubric(
        user_id=user_id, scope="user",
        name=name or "我的评分标准",
        criteria=criteria, is_customized=True,
    )
    db.add(rubric)
    db.commit()
    db.refresh(rubric)
    return rubric


def reset_rubric(db: Session, *, user_id) -> None:
    """恢复系统默认（删除用户 Rubric）。"""
    existing = db.scalar(
        select(ReviewRubric).where(ReviewRubric.user_id == user_id)
    )
    if existing:
        db.delete(existing)
        db.commit()
```

- [ ] **Step 3: Commit**

```bash
git add apps/api/app/schemas/review.py apps/api/app/services/rubric_service.py
git commit -m "feat: Rubric 服务（获取/更新/重置，用户覆盖系统）"
```

---

## 任务 2：审查引擎（确定性评估管线）

**Files:**
- Create: `apps/api/app/ai/rubric_prompts.py`
- Create: `apps/api/app/services/review_service.py`

- [ ] **Step 1: Rubric 评分 Prompt**

Create `apps/api/app/ai/rubric_prompts.py`:
```python
"""Rubric 驱动的评分 Prompt（设计 6.4）。"""


def build_score_prompt(criterion: dict, section_texts: dict) -> str:
    """为单个维度构造评分 prompt。"""
    guide_text = "\n".join(
        f"  {range_str}：{desc}" for range_str, desc in criterion.get("scoring_guide", {}).items()
    )
    content_text = "\n\n".join(
        f"【{title}】\n{text}" for title, text in section_texts.items() if text.strip()
    )
    return f"""请评估以下专利交底书在「{criterion['name']}」维度的得分。

评分标准：
{guide_text}

交底书内容：
{content_text[:3000]}

请严格按上述标准打分（0-100 整数），并给出具体证据。

输出 JSON 格式：
{{"score": 数字, "evidence": "评分依据", "suggestion": "改进建议"}}"""


SCORE_SYSTEM_PROMPT = """你是专利交底书审查专家。你的任务是根据给定的评分标准，对交底书进行客观、一致的评分。

要求：
1. 严格按评分标准打分，不要主观臆断
2. 给出具体的评分依据（引用交底书内容）
3. 提供可操作的改进建议
4. 输出必须是合法 JSON"""
```

- [ ] **Step 2: 审查服务（确定性管线）**

Create `apps/api/app/services/review_service.py`:
```python
"""审查服务：确定性评估管线（设计 6.3）。

load → score（Rubric 驱动 + 自一致性）→ aggregate → persist
"""

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.llm_client import get_llm
from app.ai.rubric_prompts import SCORE_SYSTEM_PROMPT, build_score_prompt
from app.core.exceptions import NotFoundError
from app.models import Project, ReviewRecord, Section
from app.services.rubric_service import get_effective_rubric

CONSISTENCY_RUNS = 2  # 自一致性：每维度评分次数


def run_review(db: Session, *, user_id, project_id: str) -> ReviewRecord:
    """执行完整审查。"""
    import uuid as uuid_mod
    try:
        pid = uuid_mod.UUID(project_id)
    except ValueError:
        raise NotFoundError("项目不存在")

    project = db.get(Project, pid)
    if project is None or project.user_id != user_id:
        raise NotFoundError("项目不存在")

    # ① load：加载 Rubric + 历史 + 章节内容
    rubric = get_effective_rubric(db, user_id=user_id)
    sections = _get_section_texts(db, pid)
    last_review = _get_last_review(db, pid)

    # ② score：逐维度评分（Rubric 驱动 + 自一致性）
    dimension_scores = []
    for criterion in rubric.criteria:
        scores = []
        for _ in range(CONSISTENCY_RUNS):
            score, evidence, suggestion = _score_dimension(criterion, sections)
            scores.append(score)
        avg_score = sum(scores) / len(scores)
        dimension_scores.append({
            "key": criterion["key"],
            "name": criterion["name"],
            "weight": criterion["weight"],
            "score": round(avg_score),
            "run_scores": scores,
            "evidence": evidence,
            "suggestion": suggestion,
        })

    # ③ aggregate：加权总分
    total = sum(d["score"] * d["weight"] for d in dimension_scores)

    # 对比上次
    resolved, remaining = _compare_issues(dimension_scores, last_review)

    # ④ persist
    record = ReviewRecord(
        project_id=pid,
        user_id=user_id,
        rubric_snapshot=rubric.criteria,
        round=(last_review.round + 1) if last_review else 1,
        total_score=round(total),
        previous_score=last_review.total_score if last_review else None,
        dimension_scores=dimension_scores,
        resolved_issues=resolved,
        remaining_issues=remaining,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def _get_section_texts(db: Session, project_id) -> dict[str, str]:
    """提取章节纯文本 {title: text}。"""
    from app.services.summary_service import _extract_text
    sections = list(db.scalars(
        select(Section).where(Section.project_id == project_id).order_by(Section.order)
    ))
    return {s.title: _extract_text(s.content) if s.content else "" for s in sections}


def _get_last_review(db: Session, project_id) -> ReviewRecord | None:
    """获取上一轮审查记录（跨会话记忆）。"""
    return db.scalar(
        select(ReviewRecord)
        .where(ReviewRecord.project_id == project_id)
        .order_by(ReviewRecord.created_at.desc())
    )


def _score_dimension(criterion: dict, sections: dict[str, str]) -> tuple[int, str, str]:
    """用 LLM 对单个维度评分。返回 (score, evidence, suggestion)。"""
    from langchain_core.messages import HumanMessage, SystemMessage

    llm = get_llm()
    prompt = build_score_prompt(criterion, sections)
    try:
        resp = llm.invoke([
            SystemMessage(content=SCORE_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ])
        data = _parse_json_response(resp.content)
        return (
            max(0, min(100, int(data.get("score", 50)))),
            data.get("evidence", ""),
            data.get("suggestion", ""),
        )
    except Exception:
        return (50, "评分失败", "请重试")


def _parse_json_response(text: str) -> dict:
    """从 LLM 响应解析 JSON（容错）。"""
    import re
    # 尝试提取 JSON 块
    m = re.search(r"\{[^{}]*\}", text, re.DOTALL)
    if m:
        return json.loads(m.group())
    return json.loads(text)


def _compare_issues(dimension_scores: list[dict], last_review: ReviewRecord | None) -> tuple[list, list]:
    """与上次审查对比，找出已解决/剩余问题。"""
    if not last_review:
        return [], [d["suggestion"] for d in dimension_scores if d.get("suggestion")]
    resolved = []
    remaining = []
    last_map = {d["key"]: d for d in last_review.dimension_scores}
    for d in dimension_scores:
        old = last_map.get(d["key"])
        if old and d["score"] > old["score"]:
            resolved.append(f"{d['name']} 提升（{old['score']}→{d['score']}）")
        if d.get("suggestion"):
            remaining.append(d["suggestion"])
    return resolved, remaining
```

- [ ] **Step 3: Commit**

```bash
git add apps/api/app/ai/rubric_prompts.py apps/api/app/services/review_service.py
git commit -m "feat: 审查引擎（确定性管线：load→score→aggregate→persist）"
```

---

## 任务 3：审查 + Rubric API

**Files:**
- Create: `apps/api/app/api/review.py`
- Modify: `apps/api/app/api/router.py`

- [ ] **Step 1: API 路由**

Create `apps/api/app/api/review.py`:
```python
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.deps import get_current_user
from app.models import ReviewRecord, User
from app.schemas.review import ReviewRecordOut, RubricOut, RubricUpdate
from app.services import review_service, rubric_service

router = APIRouter(tags=["review"])


# ── 审查 ──

@router.post("/projects/{project_id}/review")
def run_review(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    record = review_service.run_review(db, user_id=current_user.id, project_id=project_id)
    return _record_to_dict(record)


@router.get("/projects/{project_id}/reviews")
def list_reviews(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    records = list(db.scalars(
        select(ReviewRecord)
        .where(ReviewRecord.project_id == project_id)
        .order_by(ReviewRecord.created_at.desc())
    ))
    return [_record_to_dict(r) for r in records]


# ── Rubric ──

@router.get("/rubric", response_model=RubricOut)
def get_rubric(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rubric = rubric_service.get_effective_rubric(db, user_id=current_user.id)
    return RubricOut(
        id=str(rubric.id), scope=rubric.scope, name=rubric.name,
        criteria=rubric.criteria, is_customized=rubric.is_customized,
    )


@router.put("/rubric", response_model=RubricOut)
def update_rubric(
    payload: RubricUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rubric = rubric_service.update_user_rubric(
        db, user_id=current_user.id,
        criteria=payload.criteria or [], name=payload.name,
    )
    return RubricOut(
        id=str(rubric.id), scope=rubric.scope, name=rubric.name,
        criteria=rubric.criteria, is_customized=rubric.is_customized,
    )


@router.post("/rubric/reset", response_model=RubricOut)
def reset_rubric(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rubric_service.reset_rubric(db, user_id=current_user.id)
    rubric = rubric_service.get_effective_rubric(db, user_id=current_user.id)
    return RubricOut(
        id=str(rubric.id), scope=rubric.scope, name=rubric.name,
        criteria=rubric.criteria, is_customized=rubric.is_customized,
    )


def _record_to_dict(r: ReviewRecord) -> dict:
    return {
        "id": str(r.id),
        "round": r.round,
        "total_score": r.total_score,
        "previous_score": r.previous_score,
        "dimension_scores": r.dimension_scores,
        "resolved_issues": r.resolved_issues,
        "remaining_issues": r.remaining_issues,
        "created_at": r.created_at.isoformat(),
    }
```

注册路由到 router.py。

- [ ] **Step 2: Commit**

```bash
cd apps/api && uv run --extra dev pytest tests/ -v
git add apps/api/app/api/review.py apps/api/app/api/router.py
git commit -m "feat: 审查 + Rubric API（审查执行/历史/Rubric CRUD）"
```

---

## 任务 4：前端——审查报告页 + Rubric 配置

**Files:**
- Modify: `apps/web/src/lib/api.ts` + `types/api.ts`
- Create: `apps/web/src/app/(app)/projects/[id]/review/page.tsx`
- Create: `apps/web/src/components/rubric-editor.tsx`

- [ ] **Step 1: 类型 + API**

types/api.ts 加:
```typescript
export interface DimensionScore {
  key: string
  name: string
  weight: number
  score: number
  run_scores: number[]
  evidence: string
  suggestion: string
}

export interface ReviewRecord {
  id: string
  round: number
  total_score: number
  previous_score: number | null
  dimension_scores: DimensionScore[]
  resolved_issues: string[]
  remaining_issues: string[]
  created_at: string
}

export interface Rubric {
  id: string
  scope: string
  name: string
  criteria: RubricCriterion[]
  is_customized: boolean
}

export interface RubricCriterion {
  key: string
  name: string
  weight: number
  scoring_guide: Record<string, string>
}
```

api.ts 加:
```typescript
  runReview: (projectId: string) =>
    request<import('@/types/api').ReviewRecord>(`/projects/${projectId}/review`, { method: 'POST' }),
  listReviews: (projectId: string) =>
    request<import('@/types/api').ReviewRecord[]>(`/projects/${projectId}/reviews`),
  getRubric: () => request<import('@/types/api').Rubric>(`/rubric`),
  updateRubric: (data: { name?: string; criteria?: any[] }) =>
    request<import('@/types/api').Rubric>(`/rubric`, { method: 'PUT', body: JSON.stringify(data) }),
  resetRubric: () => request<import('@/types/api').Rubric>(`/rubric/reset`, { method: 'POST' }),
```

- [ ] **Step 2: 审查报告页**

Create `apps/web/src/app/(app)/projects/[id]/review/page.tsx`:
```tsx
'use client'

import { useParams } from 'next/navigation'
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { api } from '@/lib/api'
import type { ReviewRecord } from '@/types/api'

export default function ReviewPage() {
  const params = useParams<{ id: string }>()
  const qc = useQueryClient()
  const [reviewing, setReviewing] = useState(false)

  const { data: reviews } = useQuery({
    queryKey: ['reviews', params.id],
    queryFn: () => api.listReviews(params.id),
  })

  const latest: ReviewRecord | undefined = reviews?.[0]

  const runReview = useMutation({
    mutationFn: () => api.runReview(params.id),
    onMutate: () => setReviewing(true),
    onSuccess: () => {
      toast.success('审查完成')
      qc.invalidateQueries({ queryKey: ['reviews', params.id] })
    },
    onError: () => toast.error('审查失败'),
    onSettled: () => setReviewing(false),
  })

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold">交底书审查</h1>
        <Button onClick={() => runReview.mutate()} disabled={reviewing}>
          {reviewing ? '审查中...' : '执行审查'}
        </Button>
      </div>

      {latest ? (
        <div className="space-y-4">
          {/* 总分 */}
          <div className="rounded-lg border p-6 text-center">
            <div className="text-4xl font-bold">{latest.total_score}</div>
            <div className="text-sm text-muted-foreground">总分（第 {latest.round} 轮）</div>
            {latest.previous_score !== null && (
              <Badge variant={latest.total_score >= latest.previous_score ? 'default' : 'destructive'} className="mt-2">
                {latest.total_score >= latest.previous_score ? '+' : ''}
                {latest.total_score - latest.previous_score}
              </Badge>
            )}
          </div>

          {/* 各维度 */}
          {latest.dimension_scores.map((d) => (
            <div key={d.key} className="rounded-lg border p-4 space-y-2">
              <div className="flex items-center justify-between">
                <span className="font-medium">{d.name}</span>
                <span className="text-lg font-bold">{d.score}</span>
              </div>
              <p className="text-xs text-muted-foreground">权重 {Math.round(d.weight * 100)}%</p>
              {d.evidence && <p className="text-sm">依据：{d.evidence}</p>}
              {d.suggestion && <p className="text-sm text-muted-foreground">建议：{d.suggestion}</p>}
              <p className="text-xs text-muted-foreground">
                自一致性评分：{d.run_scores.join(' / ')}
              </p>
            </div>
          ))}

          {/* 已解决/剩余问题 */}
          {latest.resolved_issues.length > 0 && (
            <div className="rounded-lg border border-green-200 bg-green-50 p-4">
              <h3 className="text-sm font-semibold text-green-800">已解决的问题</h3>
              <ul className="mt-2 space-y-1 text-sm">
                {latest.resolved_issues.map((issue, i) => (
                  <li key={i}>✓ {issue}</li>
                ))}
              </ul>
            </div>
          )}
          {latest.remaining_issues.length > 0 && (
            <div className="rounded-lg border border-amber-200 bg-amber-50 p-4">
              <h3 className="text-sm font-semibold text-amber-800">待改进</h3>
              <ul className="mt-2 space-y-1 text-sm">
                {latest.remaining_issues.map((issue, i) => (
                  <li key={i}>→ {issue}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      ) : (
        <p className="text-center text-muted-foreground py-12">
          尚未审查，点击「执行审查」开始
        </p>
      )}
    </div>
  )
}
```

- [ ] **Step 3: Rubric 配置（简化版：展示 + 重置）**

Create `apps/web/src/components/rubric-editor.tsx`:
```tsx
'use client'

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { api } from '@/lib/api'

export function RubricEditor() {
  const qc = useQueryClient()
  const { data: rubric } = useQuery({
    queryKey: ['rubric'],
    queryFn: () => api.getRubric(),
  })

  const reset = useMutation({
    mutationFn: () => api.resetRubric(),
    onSuccess: () => {
      toast.success('已恢复系统默认')
      qc.invalidateQueries({ queryKey: ['rubric'] })
    },
  })

  if (!rubric) return <p className="text-muted-foreground">加载中...</p>

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold">{rubric.name}</h1>
          <p className="text-sm text-muted-foreground">
            {rubric.is_customized ? '已自定义' : '系统默认'}
          </p>
        </div>
        {rubric.is_customized && (
          <Button variant="outline" onClick={() => reset.mutate()}>恢复默认</Button>
        )}
      </div>

      <div className="space-y-3">
        {rubric.criteria.map((c) => (
          <div key={c.key} className="rounded-lg border p-4">
            <div className="flex items-center gap-2">
              <span className="font-medium">{c.name}</span>
              <Badge variant="secondary">权重 {Math.round(c.weight * 100)}%</Badge>
            </div>
            <div className="mt-2 space-y-1 text-sm text-muted-foreground">
              {Object.entries(c.scoring_guide).map(([range, desc]) => (
                <p key={range}><strong>{range}</strong>：{desc}</p>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
```

- [ ] **Step 4: 构建验证 + Commit**

navbar 加审查/设置入口（可选）。

```bash
cd apps/web && pnpm build
git add apps/web/
git commit -m "feat: 前端审查报告页 + Rubric 配置展示"
```

---

## 任务 5：端到端验证（真实审查 + 稳定性）

- [ ] **Step 1: 种子 + 启动**

```bash
cd apps/api && uv run python -c "from app.core.database import SessionLocal; from app.services.seed_service import ensure_default_rubric; db=SessionLocal(); ensure_default_rubric(db); db.close(); print('rubric seeded')"
cd apps/api && uv run uvicorn app.main:app --reload
```

- [ ] **Step 2: 验证审查流程**

```bash
# 登录 → 创建项目 → 填充章节 → 执行审查 → 查看报告
# 再次审查 → 验证分数稳定（标准差 ≤ 3）
```

- [ ] **Step 3: Commit**

```bash
git commit --allow-empty -m "chore: 计划 7 审查引擎端到端验证通过"
```

---

## 完成标准

- [ ] ReviewRubric/ReviewRecord 模型 + 默认 Rubric 种子
- [ ] Rubric 服务（获取/更新/重置，用户覆盖系统）
- [ ] 审查引擎（确定性管线：load→score→aggregate→persist）
- [ ] Rubric 驱动评分 + 自一致性（N=2 取均值）
- [ ] 跨会话记忆（ReviewRecord 加载上次记录）
- [ ] 审查 + Rubric API
- [ ] 前端审查报告页 + Rubric 配置
- [ ] 端到端验证通过

## 后续（计划 7b，不在本计划）

- 管理员后台（全局模板/Rubric/用户管理）
- LLM 自定义配置（用户自配 key）
- agent 技能自定义
