# apps/api/app/api/admin/skills.py
"""admin 全局技能管理路由（/admin/skills/*）。

仿 admin/content.py 模式：require_admin + 委托 skill_service + 返回 SkillOut。
管理 scope=global 的技能（owner_id=NULL）。
"""
from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.exceptions import ValidationError
from app.deps import require_admin
from app.models import User
from app.models.skill import SCOPE_GLOBAL
from app.schemas.skill import SkillCreate, SkillDetail, SkillOut, SkillUpdate
from app.skills import service as skill_service

router = APIRouter(tags=["admin"])


def _to_out(skill) -> SkillOut:
    """Skill ORM → SkillOut（UUID/datetime 显式转 str）。

    不依赖 from_attributes 自动转换：显式 isoformat()/str() 更稳，
    避免 Pydantic 在 UUID→str/None owner 上的边角差异。
    """
    return SkillOut(
        id=str(skill.id),
        name=skill.name,
        description=skill.description,
        scope=skill.scope,
        owner_id=str(skill.owner_id) if skill.owner_id else None,
        status=skill.status,
        minio_prefix=skill.minio_prefix,
        created_at=skill.created_at.isoformat() if skill.created_at else "",
        updated_at=skill.updated_at.isoformat() if skill.updated_at else "",
    )


@router.get("/admin/skills", response_model=list[SkillOut])
def list_global_skills(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """列出所有全局 skill（owner_id=NULL，scope=global）。"""
    skills = skill_service.list_skills(db, scope=SCOPE_GLOBAL, owner_id=None)
    return [_to_out(s) for s in skills]


@router.post("/admin/skills", response_model=SkillOut)
def create_global_skill(
    payload: SkillCreate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """创建全局 skill（默认 draft）。scope 由路由决定，不在 body。"""
    skill = skill_service.create_skill(
        db, scope=SCOPE_GLOBAL, owner_id=None,
        name=payload.name, description=payload.description, body=payload.skill_md,
    )
    return _to_out(skill)


@router.get("/admin/skills/{skill_id}", response_model=SkillDetail)
def get_global_skill(
    skill_id: str,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """获取全局 skill 详情（含 SKILL.md 全文，含 frontmatter）。"""
    skill, md = skill_service.read_skill_detail(db, skill_id=skill_id)
    out = _to_out(skill)
    return SkillDetail(**out.model_dump(), skill_md=md)


@router.put("/admin/skills/{skill_id}", response_model=SkillOut)
def update_global_skill(
    skill_id: str,
    payload: SkillUpdate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """更新全局 skill。name 不可改（service 层忽略）。

    若只改 description 未带 skill_md，回读当前 SKILL.md 正文一并传给 service，
    使 MinIO frontmatter 的 description 重新同步（Task 16 review 指出的同步缺口）。
    """
    fields = payload.model_dump(exclude_unset=True)
    if "description" in fields and "skill_md" not in fields:
        _, md = skill_service.read_skill_detail(db, skill_id=skill_id)
        # read_skill_md 返回含 frontmatter 的全文；正文取首个 '---' 块之后部分
        body = md.split("---\n", 2)[-1].lstrip("\n") if "---\n" in md else md
        fields["skill_md"] = body
    skill = skill_service.update_skill(db, skill_id=skill_id, **fields)
    return _to_out(skill)


@router.delete("/admin/skills/{skill_id}")
def delete_global_skill(
    skill_id: str,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """删除全局 skill（DB + MinIO 目录，幂等）。"""
    skill_service.delete_skill(db, skill_id=skill_id)
    return {"ok": True}


@router.post("/admin/skills/import-zip", response_model=SkillOut)
async def import_global_skill_zip(
    file: UploadFile = File(...),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """从 zip 包导入全局 skill（spec 标准 SKILL.md + scripts/references/assets）。

    同名拒绝（ConflictError）。默认 status=draft，导入后需手动激活。
    """
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise ValidationError("仅支持 .zip 文件")
    content = await file.read()
    skill = skill_service.import_skill_zip(
        db, scope=SCOPE_GLOBAL, owner_id=None, zip_bytes=content,
    )
    return _to_out(skill)
