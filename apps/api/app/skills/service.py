# apps/api/app/skills/service.py
"""Skill 业务逻辑：目录管理（本文件）+ 可见性合并（visibility.py）+ CRUD（Task 16 补）。

目录管理：把 frontmatter + 正文拼成 SKILL.md 存 MinIO，管理 scripts/references/assets。
"""
from app.core import storage as _storage_mod
from app.core.exceptions import NotFoundError

SKILL_MD_FILENAME = "SKILL.md"


def assemble_skill_md(*, name: str, description: str, body: str) -> str:
    """组装完整 SKILL.md = frontmatter + 正文。

    description 必须单行（spec 触发条件约束），调用方负责校验。
    """
    return f"---\nname: {name}\ndescription: {description}\n---\n\n{body}"


def _key(prefix: str, filename: str) -> str:
    return f"{prefix}{filename}"


def write_skill_directory(
    *, bucket: str, prefix: str, name: str, description: str, body: str,
    scripts: dict[str, str] | None = None,
    references: dict[str, str] | None = None,
    assets: dict[str, bytes] | None = None,
) -> None:
    """写一个完整 skill 目录到 MinIO。"""
    st = _storage_mod.get_storage()
    # SKILL.md
    st.put(
        bucket, _key(prefix, SKILL_MD_FILENAME),
        assemble_skill_md(name=name, description=description, body=body).encode("utf-8"),
        "text/markdown",
    )
    # scripts/
    for fname, code in (scripts or {}).items():
        st.put(bucket, _key(prefix, f"scripts/{fname}"), code.encode("utf-8"), "text/plain")
    # references/
    for fname, text in (references or {}).items():
        st.put(bucket, _key(prefix, f"references/{fname}"), text.encode("utf-8"), "text/plain")
    # assets/（二进制）
    for fname, data in (assets or {}).items():
        st.put(bucket, _key(prefix, f"assets/{fname}"), data, "application/octet-stream")


def read_skill_md(*, bucket: str, prefix: str) -> str:
    """读 SKILL.md 正文。不存在抛 NotFoundError。"""
    st = _storage_mod.get_storage()
    key = _key(prefix, SKILL_MD_FILENAME)
    if not st.stat(bucket, key):
        raise NotFoundError(f"Skill 不存在：{prefix}")
    return st.get(bucket, key).decode("utf-8")


def delete_skill_directory(*, bucket: str, prefix: str) -> None:
    """删 skill 目录：清空该 prefix 下所有对象（幂等）。"""
    st = _storage_mod.get_storage()
    client = st._client  # noqa: SLF001（复用已建连的 client，Storage Protocol 无 list 方法）
    real_bucket = st._resolve(bucket)  # noqa: SLF001
    objs = list(client.list_objects(real_bucket, prefix=prefix, recursive=True))
    for obj in objs:
        client.remove_object(real_bucket, obj.object_name)


# ── CRUD（DB + MinIO 协同）──

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError
from app.models.skill import SCOPE_GLOBAL, STATUS_DRAFT, Skill


def _minio_prefix(*, scope: str, owner_id, name: str) -> str:
    """构造 minio_prefix（编码 scope + owner）。"""
    if scope == SCOPE_GLOBAL:
        return f"skills/global/{name}/"
    return f"skills/personal/{owner_id}/{name}/"


def _bucket_for_scope(scope: str) -> str:
    """所有 skill 统一用 global bucket（C1 决定，Task 12 fix）。

    scope 仅靠 minio_prefix 区分，不拆分 bucket。
    """
    return "global"


def create_skill(
    db: Session, *, scope: str, owner_id, name: str, description: str, body: str,
    scripts: dict[str, str] | None = None,
    references: dict[str, str] | None = None,
    status: str = STATUS_DRAFT,
) -> Skill:
    """创建 skill：DB 行 + MinIO 目录。name 唯一性校验。"""
    # 唯一性校验（匹配 partial unique index 的语义）
    if owner_id is not None:
        existing = db.scalar(select(Skill).where(
            Skill.scope == scope, Skill.owner_id == owner_id, Skill.name == name,
        ))
    else:
        existing = db.scalar(select(Skill).where(
            Skill.scope == scope, Skill.owner_id.is_(None), Skill.name == name,
        ))
    if existing:
        raise ConflictError(f"技能名「{name}」已存在")

    prefix = _minio_prefix(scope=scope, owner_id=owner_id, name=name)
    bucket = _bucket_for_scope(scope)

    # 先写 MinIO 目录
    write_skill_directory(
        bucket=bucket, prefix=prefix, name=name, description=description, body=body,
        scripts=scripts, references=references,
    )

    # 再写 DB
    skill = Skill(
        name=name, description=description, scope=scope,
        owner_id=owner_id, status=status, minio_prefix=prefix,
    )
    db.add(skill)
    db.commit()
    db.refresh(skill)
    return skill


def get_skill(db: Session, *, skill_id) -> Skill:
    from uuid import UUID
    sid = UUID(str(skill_id)) if isinstance(skill_id, str) else skill_id
    skill = db.get(Skill, sid)
    if skill is None:
        raise NotFoundError("技能不存在")
    return skill


def update_skill(db: Session, *, skill_id, **fields) -> Skill:
    """更新 skill。name 不可改（spec: name=目录名）。"""
    skill = get_skill(db, skill_id=skill_id)
    for k, v in fields.items():
        if k == "name":
            continue  # 忽略 name 改动
        if hasattr(skill, k) and v is not None:
            setattr(skill, k, v)
    db.commit()
    db.refresh(skill)

    # 若 description 或 skill_md（body）变了，同步 MinIO 的 SKILL.md
    body = fields.get("skill_md")
    if body and ("description" in fields or "skill_md" in fields):
        bucket = _bucket_for_scope(skill.scope)
        st = _storage_mod.get_storage()
        st.put(
            bucket, _key(skill.minio_prefix, SKILL_MD_FILENAME),
            assemble_skill_md(name=skill.name, description=skill.description, body=body).encode("utf-8"),
            "text/markdown",
        )
    return skill


def delete_skill(db: Session, *, skill_id) -> None:
    skill = get_skill(db, skill_id=skill_id)
    bucket = _bucket_for_scope(skill.scope)
    delete_skill_directory(bucket=bucket, prefix=skill.minio_prefix)
    db.delete(skill)
    db.commit()


def list_skills(db: Session, *, scope: str, owner_id) -> list[Skill]:
    """按 scope + owner 列出（admin 列 global，user 列自己的 personal）。"""
    if owner_id is not None:
        stmt = select(Skill).where(Skill.scope == scope, Skill.owner_id == owner_id)
    else:
        stmt = select(Skill).where(Skill.scope == scope, Skill.owner_id.is_(None))
    stmt = stmt.order_by(Skill.created_at.desc())
    return list(db.scalars(stmt))


def read_skill_detail(db: Session, *, skill_id) -> tuple[Skill, str]:
    """读详情：skill 元数据 + SKILL.md 正文。"""
    skill = get_skill(db, skill_id=skill_id)
    bucket = _bucket_for_scope(skill.scope)
    md = read_skill_md(bucket=bucket, prefix=skill.minio_prefix)
    return skill, md


def import_skill_zip(db: Session, *, scope: str, owner_id, zip_bytes: bytes) -> Skill:
    """从 zip 包导入 skill：解析 → 复用 create_skill（唯一性 + MinIO + DB）。

    zip 解析失败（缺 SKILL.md、路径穿越、frontmatter 缺字段、name 不合规）
    抛 ValidationError。同名抛 ConflictError（来自 create_skill）。
    默认 status=draft（导入后用户手动激活）。
    """
    from app.skills.zip_import import parse_skill_zip

    parsed = parse_skill_zip(zip_bytes)
    return create_skill(
        db, scope=scope, owner_id=owner_id,
        name=parsed.name, description=parsed.description, body=parsed.body,
        scripts=parsed.scripts, references=parsed.references, assets=parsed.assets,
    )
