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
from app.services import llm_config_service
from app.services.rubric_service import get_effective_rubric
from app.services.skill_service import is_skill_enabled

CONSISTENCY_RUNS = 2  # 自一致性：每维度评分次数（consistency_check 启用）


def run_review(db: Session, *, user_id, project_id: str) -> ReviewRecord:
    """执行完整审查。"""
    try:
        pid = uuid_mod.UUID(project_id)
    except ValueError:
        raise NotFoundError("项目不存在")

    project = db.get(Project, pid)
    if project is None or project.user_id != user_id:
        raise NotFoundError("项目不存在")

    # 设计 7.4：rubric_review 禁用则拒绝审查
    if not is_skill_enabled(db, project_id=pid, skill_key="rubric_review"):
        raise ValidationError("已禁用 Rubric 审查技能")
    # consistency_check 禁用则每维度只跑一次
    runs = CONSISTENCY_RUNS if is_skill_enabled(
        db, project_id=pid, skill_key="consistency_check"
    ) else 1

    # ① load
    rubric = get_effective_rubric(db, user_id=user_id)
    sections = _get_section_texts(db, pid)
    last_review = _get_last_review(db, pid)

    # ② score（Rubric 驱动 + 自一致性）
    dimension_scores = []
    for criterion in rubric.criteria:
        scores = []
        last_evidence = ""
        last_suggestion = ""
        for _ in range(runs):
            score, evidence, suggestion = _score_dimension(db, user_id, criterion, sections)
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


def _score_dimension(db: Session, user_id, criterion: dict, sections: dict[str, str]) -> tuple[int, str, str]:
    """单维度评分。透传用户/全局 LLM 配置（BYOK 生效）。"""
    try:
        cfg = llm_config_service.resolve_llm_config(db, user_id=user_id)
    except Exception:
        cfg = None
    llm = get_llm(
        **({"base_url": cfg.base_url or None, "api_key": cfg.api_key or None, "model": cfg.model or None} if cfg else {})
    )
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
