from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.deps import get_current_user
from app.models import User
from app.schemas.diff import ApplyDiffRequest, DiffRequest, DiffResponse, RewriteDiffRequest
from app.schemas.section import SectionOut, SectionUpdate
from app.services import diff_service, section_service

router = APIRouter(tags=["sections"])


def _to_out(s) -> SectionOut:
    return SectionOut(
        id=str(s.id), project_id=str(s.project_id), order=s.order, key=s.key,
        title=s.title, content=s.content, summary=s.summary, status=s.status,
        version=s.version, created_at=s.created_at, updated_at=s.updated_at,
    )


@router.get("/projects/{project_id}/sections", response_model=list[SectionOut])
def list_sections(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    sections = section_service.list_sections(
        db, user_id=current_user.id, project_id=project_id
    )
    return [_to_out(s) for s in sections]


@router.get("/sections/{section_id}", response_model=SectionOut)
def get_section(
    section_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    s = section_service.get_section(db, user_id=current_user.id, section_id=section_id)
    return _to_out(s)


@router.patch("/sections/{section_id}", response_model=SectionOut)
def update_section(
    section_id: str,
    payload: SectionUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    s = section_service.update_section(
        db, user_id=current_user.id, section_id=section_id,
        content=payload.content, status=payload.status,
        expected_version=payload.expected_version,
    )
    return _to_out(s)


@router.post("/sections/{section_id}/diff", response_model=DiffResponse)
def compute_diff(
    section_id: str,
    payload: DiffRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """计算 AI 草稿与当前章节内容的 diff。"""
    from app.services.export_service import _tiptap_to_markdown
    section = section_service.get_section(db, user_id=current_user.id, section_id=section_id)
    original_text = _tiptap_to_markdown(section.content) if section.content else ""
    hunks = diff_service.compute_section_diff(original_text, payload.ai_text)
    return DiffResponse(hunks=hunks)


@router.post("/sections/{section_id}/apply-diff", response_model=SectionOut)
def apply_diff(
    section_id: str,
    payload: ApplyDiffRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """应用用户接受的 diff hunks 到章节内容。"""
    section = diff_service.apply_diff_to_section(
        db, user_id=current_user.id, section_id=section_id,
        ai_text=payload.ai_text, accepted_hunk_ids=payload.accepted_hunk_ids,
        expected_version=payload.expected_version,
    )
    return _to_out(section)


@router.post("/sections/{section_id}/rewrite-diff", response_model=DiffResponse)
def compute_rewrite_diff(
    section_id: str,
    payload: RewriteDiffRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """计算选区重写的整章 diff（方案 B：后端拼接原文 + AI 输出，spec §3.4）。

    与 /diff 区别：本端点接收 selected_text + ai_text，后端做"首次出现替换"拼接，
    再调 compute_section_diff。前端无需自行实现 Tiptap→markdown 转换。
    """
    section = section_service.get_section(db, user_id=current_user.id, section_id=section_id)
    hunks = diff_service.compute_rewrite_diff(section, payload.selected_text, payload.ai_text)
    return DiffResponse(hunks=hunks)
