from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.exceptions import ValidationError
from app.deps import get_current_user
from app.models import Project, Section, User
from app.schemas.project import ProjectCreate, ProjectOut, ProjectUpdate
from app.schemas.skill import SkillOut, SkillUpdate
from app.services import archive_service, project_service, skill_service

router = APIRouter(prefix="/projects", tags=["projects"])


def _to_out(p: Project) -> ProjectOut:
    return ProjectOut(
        id=str(p.id), title=p.title, stage=p.stage, status=p.status,
        progress_pct=p.progress_pct, metadata=p.metadata_,
        archived_at=p.archived_at, created_at=p.created_at, updated_at=p.updated_at,
    )


@router.post("", response_model=ProjectOut, status_code=201)
def create(payload: ProjectCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    p = project_service.create_project(
        db, user=current_user, title=payload.title,
        template_id=payload.template_id, metadata=payload.metadata,
    )
    return _to_out(p)


@router.get("", response_model=list[ProjectOut])
def list_all(
    status: str | None = None,
    q: str | None = None,
    tag_id: str | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    projects = project_service.list_projects(
        db, user=current_user, status=status, q=q, tag_id=tag_id,
    )
    return [_to_out(p) for p in projects]


@router.get("/{project_id}", response_model=ProjectOut)
def get_one(project_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    p = project_service.get_project(db, user=current_user, project_id=project_id)
    return _to_out(p)


@router.patch("/{project_id}", response_model=ProjectOut)
def update(project_id: str, payload: ProjectUpdate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    p = project_service.update_project(
        db, user=current_user, project_id=project_id,
        title=payload.title, metadata=payload.metadata,
    )
    return _to_out(p)


@router.delete("/{project_id}", status_code=204)
def delete(project_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project_service.delete_project(db, user=current_user, project_id=project_id)
    return None


@router.post("/{project_id}/archive")
def archive(project_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # 归属校验：非本人项目返回 404（防探测，与其他端点一致）
    project = project_service.get_project(db, user=current_user, project_id=project_id)

    # 前置校验：至少一个非空 confirmed 章节（防空项目造垃圾 chunk，spec §6.2）
    has_confirmed = db.scalar(
        select(Section).where(
            (Section.project_id == project.id)
            & (Section.status == "confirmed")
            & (Section.content.is_not(None))
        ).limit(1)
    )
    if has_confirmed is None:
        raise ValidationError("内容不足，无法归档（需至少一个已确认的非空章节）")

    # archive_service.archive 内部二次校验归属并调 rag/archiver（幂等：先删旧 chunk 再重生）
    return archive_service.archive(db, user_id=current_user.id, project_id=project_id)


@router.get("/{project_id}/skills", response_model=list[SkillOut])
def list_skills(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """列出项目所有技能（builtin + 覆盖）。"""
    project = project_service.get_project(db, user=current_user, project_id=project_id)
    rows = skill_service.list_skills(db, project_id=project.id)
    return [SkillOut(**r) for r in rows]


@router.put("/{project_id}/skills/{skill_key}", response_model=SkillOut)
def update_skill(
    project_id: str,
    skill_key: str,
    payload: SkillUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """更新项目技能开关。"""
    project = project_service.get_project(db, user=current_user, project_id=project_id)
    skill_service.set_skill(
        db, project_id=project.id, skill_key=skill_key,
        enabled=payload.enabled, config=payload.config,
    )
    # 用 list_skills 取合并后的视图（含 builtin name/description）
    row = next(
        r for r in skill_service.list_skills(db, project_id=project.id)
        if r["skill_key"] == skill_key
    )
    return SkillOut(**row)
