# apps/api/app/api/skills.py
"""用户个人技能路由（/skills/*）。

- /skills/mine：个人 skill CRUD（仅本人可操作）
- /skills/visible：可见 skill 列表（global active ∪ 自己的 personal active）

权限：get_current_user（JWT cookie）。
归属校验在路由层：personal skill 仅 owner 本人可读写，
否则抛 ForbiddenError（显式拒绝，防 ID 探测）。
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.exceptions import ForbiddenError
from app.deps import get_current_user
from app.models import User
from app.models.skill import SCOPE_PERSONAL
from app.schemas.skill import SkillCreate, SkillDetail, SkillOut, SkillUpdate
from app.skills import service as skill_service
from app.skills.visibility import list_visible_skills

router = APIRouter()


def _to_out(skill) -> SkillOut:
    """Skill ORM → SkillOut（UUID/datetime 显式转 str）。

    与 admin/skills.py 一致：不依赖 from_attributes 自动转换，
    显式 isoformat()/str() 更稳。
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


def _check_ownership(skill, user_id) -> None:
    """归属校验：personal skill 仅 owner 本人可操作，否则 ForbiddenError。

    防探测：不返回 404（透露存在性），显式 403 表明无权。
    global skill 不应进入 /skills/mine 路径，亦拒绝。
    """
    if skill.scope != SCOPE_PERSONAL or skill.owner_id != user_id:
        raise ForbiddenError("无权访问该技能")


@router.get("/skills/visible", response_model=list[SkillOut])
def list_my_visible_skills(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """列出当前用户可见的所有 active skill（global ∪ 自己的 personal）。"""
    skills = list_visible_skills(db, user_id=current_user.id)
    return [_to_out(s) for s in skills]


@router.get("/skills/mine", response_model=list[SkillOut])
def list_my_personal_skills(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """列出我的个人 skill（含 draft）。"""
    skills = skill_service.list_skills(db, scope=SCOPE_PERSONAL, owner_id=current_user.id)
    return [_to_out(s) for s in skills]


@router.post("/skills/mine", response_model=SkillOut)
def create_personal_skill(
    payload: SkillCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """创建个人 skill（默认 draft）。scope 由路由决定，不在 body。"""
    skill = skill_service.create_skill(
        db, scope=SCOPE_PERSONAL, owner_id=current_user.id,
        name=payload.name, description=payload.description, body=payload.skill_md,
    )
    return _to_out(skill)


@router.get("/skills/mine/{skill_id}", response_model=SkillDetail)
def get_my_skill(
    skill_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取我的 skill 详情（含 SKILL.md 全文）。归属校验防探测。"""
    skill, md = skill_service.read_skill_detail(db, skill_id=skill_id)
    _check_ownership(skill, current_user.id)
    out = _to_out(skill)
    return SkillDetail(**out.model_dump(), skill_md=md)


@router.put("/skills/mine/{skill_id}", response_model=SkillOut)
def update_my_skill(
    skill_id: str,
    payload: SkillUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """更新我的 skill。name 不可改（service 层忽略）。

    若只改 description 未带 skill_md，回读当前 SKILL.md 正文一并传给 service，
    使 MinIO frontmatter 的 description 重新同步（与 admin 路由一致）。
    """
    skill = skill_service.get_skill(db, skill_id=skill_id)
    _check_ownership(skill, current_user.id)
    fields = payload.model_dump(exclude_unset=True)
    if "description" in fields and "skill_md" not in fields:
        _, md = skill_service.read_skill_detail(db, skill_id=skill_id)
        # read_skill_md 返回含 frontmatter 全文；正文取首个 '---' 块之后部分
        body = md.split("---\n", 2)[-1].lstrip("\n") if "---\n" in md else md
        fields["skill_md"] = body
    skill = skill_service.update_skill(db, skill_id=skill_id, **fields)
    return _to_out(skill)


@router.delete("/skills/mine/{skill_id}")
def delete_my_skill(
    skill_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """删除我的 skill（DB + MinIO 目录，幂等）。归属校验防探测。"""
    skill = skill_service.get_skill(db, skill_id=skill_id)
    _check_ownership(skill, current_user.id)
    skill_service.delete_skill(db, skill_id=skill_id)
    return {"ok": True}
