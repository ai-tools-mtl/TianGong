"""项目术语表路由（T2 spec §3.3.2）。全部经 project/term 归属校验（越权 404）。"""
import time

from fastapi import APIRouter, Body, Depends, Request
from loguru import logger
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.rate_limit import AI_LIMIT, _user_or_ip_key, limiter
from app.deps import get_current_user
from app.models import User
from app.schemas.term import CheckRequest, TermCreate, TermUpdate
from app.services import term_service

router = APIRouter(tags=["terms"])


def _iso(v) -> str:
    return v.isoformat() if v is not None else None


def _term_out(t) -> dict:
    return {
        "id": str(t.id), "project_id": str(t.project_id),
        "term": t.term, "definition": t.definition,
        "variants": t.variants or [], "enabled": t.enabled, "source": t.source,
        "created_at": _iso(t.created_at), "updated_at": _iso(t.updated_at),
    }


@router.get("/projects/{project_id}/terms")
def list_terms(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = term_service.list_terms(db, user_id=current_user.id, project_id=project_id)
    return [_term_out(t) for t in rows]


@router.post("/projects/{project_id}/terms")
def create_term(
    project_id: str,
    payload: TermCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = term_service.create_term(
        db, user_id=current_user.id, project_id=project_id,
        term=payload.term.strip(), definition=payload.definition,
        variants=payload.variants, source=payload.source if payload.source in ("manual", "ai") else "manual",
    )
    return _term_out(row)


@router.put("/terms/{term_id}")
def update_term(
    term_id: str,
    payload: TermUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = term_service.update_term(
        db, user_id=current_user.id, term_id=term_id,
        term=payload.term, definition=payload.definition,
        variants=payload.variants, enabled=payload.enabled,
    )
    return _term_out(row)


@router.delete("/terms/{term_id}")
def delete_term(
    term_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    term_service.delete_term(db, user_id=current_user.id, term_id=term_id)
    return {"ok": True}


@router.post("/projects/{project_id}/terms/extract")
@limiter.limit(AI_LIMIT, key_func=_user_or_ip_key)
async def extract_terms(
    request: Request,
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """AI 抽取候选术语（lite；候选不入库，前端勾选后逐条 POST /terms）。"""
    start = time.monotonic()
    result = term_service.extract_candidates(db, user_id=current_user.id, project_id=project_id)
    _log(db, current_user.id, project_id, "terms_extract",
         failed=bool(result.get("warning")), start=start)
    return result


@router.post("/projects/{project_id}/terms/check")
@limiter.limit(AI_LIMIT, key_func=_user_or_ip_key)
async def check_terms(
    request: Request,
    project_id: str,
    payload: CheckRequest | None = Body(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """一致性检查：规则路（零 token）+ LLM 路（表外漂移，fail-open）+ 可选 llm_verify。"""
    start = time.monotonic()
    result = term_service.check_consistency(
        db, user_id=current_user.id, project_id=project_id,
        llm_verify=payload.llm_verify if payload else False,
    )
    _log(db, current_user.id, project_id, "terms_check",
         failed=bool(result.get("warning")), start=start)
    return result


def _log(db, user_id, project_id, action: str, *, failed: bool, start: float) -> None:
    """尽力记账（失败不阻断主流程）。"""
    try:
        from app.api.ai import _log_llm_call
        _log_llm_call(
            db, user_id=user_id, project_id=project_id, action=action,
            model=None, provider=None,
            status="failed" if failed else "success",
            duration_ms=int((time.monotonic() - start) * 1000),
            error=action if failed else None,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("terms %s 记账失败: %s", action, e)
