"""审查服务：确定性评估管线（设计 6.3）。

load → score（Rubric 驱动 + 自一致性）→ aggregate → persist
"""

import json
import re
import uuid as uuid_mod

from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.llm_client import get_llm
from app.ai.rubric_prompts import SCORE_SYSTEM_PROMPT, build_score_prompt
from app.core.exceptions import NotFoundError, ValidationError
from app.models import Project, ReviewRecord, Section
from app.services.llm_config_service import ResolvedLLMConfig, resolve_llm_config
from app.services.rubric_service import get_effective_rubric

CONSISTENCY_RUNS = 2  # 自一致性：每维度评分次数（旧 consistency_check skill 已删除，默认开启）


def run_review(db: Session, *, user_id, project_id: str) -> ReviewRecord:
    """执行完整审查。"""
    try:
        pid = uuid_mod.UUID(project_id)
    except ValueError:
        raise NotFoundError("项目不存在")

    project = db.get(Project, pid)
    if project is None or project.user_id != user_id:
        raise NotFoundError("项目不存在")

    # 旧 project-scoped skill 开关已删除（spec Q5 解耦）。
    # rubric_review / consistency_check 默认全开；后续按 spec 用全局/用户级 Skill 重建（Task 6+）。
    runs = CONSISTENCY_RUNS

    # ① load
    rubric = get_effective_rubric(db, user_id=user_id)
    sections = _get_section_texts(db, pid)
    last_review = _get_last_review(db, pid)

    # 阶段 0：解析生效 LLM 配置（断链修复：审查调用真驱动 LLM）。无配置直接拒绝。
    llm_config = resolve_llm_config(db, user_id=user_id)
    if llm_config is None:
        raise ValidationError("未配置 LLM，无法执行审查")

    # ② score（Rubric 驱动 + 自一致性）
    dimension_scores = []
    for criterion in rubric.criteria:
        scores = []
        last_evidence = ""
        last_suggestion = ""
        for _ in range(runs):
            score, evidence, suggestion = _score_dimension(criterion, sections, llm_config)
            scores.append(score)
            last_evidence = evidence
            last_suggestion = suggestion
        avg_score = sum(scores) / len(scores)
        dimension_scores.append({
            "key": criterion["key"],
            "name": criterion["name"],
            "weight": criterion["weight"],
            "score": round(avg_score),
            "run_scores": scores,
            "evidence": last_evidence,
            "suggestion": last_suggestion,
        })

    # ③ aggregate
    total = sum(d["score"] * d["weight"] for d in dimension_scores)
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
    from app.services.summary_service import _extract_text
    sections = list(db.scalars(
        select(Section).where(Section.project_id == project_id).order_by(Section.order)
    ))
    return {s.title: _extract_text(s.content) if s.content else "" for s in sections}


def _get_last_review(db: Session, project_id) -> ReviewRecord | None:
    return db.scalar(
        select(ReviewRecord)
        .where(ReviewRecord.project_id == project_id)
        .order_by(ReviewRecord.created_at.desc())
    )


def _score_dimension(
    criterion: dict, sections: dict[str, str], llm_config: ResolvedLLMConfig
) -> tuple[int, str, str]:
    llm = get_llm(llm_config)
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
    m = re.search(r"\{[^{}]*\}", text, re.DOTALL)
    if m:
        return json.loads(m.group())
    return json.loads(text)


def _compare_issues(
    dimension_scores: list[dict], last_review: ReviewRecord | None
) -> tuple[list, list]:
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
