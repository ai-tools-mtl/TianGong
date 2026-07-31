# apps/api/app/skills/visibility.py
"""可见性合并服务（spec Q11-α）。

每次 agent run 纯运行时计算可见 skill 集合：
  visible = {scope=global, status=active} ∪ {scope=personal, owner=user, status=active}

项目不持有 skill 状态，下线即不可见（无孤儿问题）。
"""
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.skill import SCOPE_GLOBAL, SCOPE_PERSONAL, STATUS_ACTIVE, Skill


def list_visible_skills(db: Session, *, user_id) -> list[Skill]:
    """返回 user 当前可见的所有 active skill（global ∪ personal）。"""
    stmt = select(Skill).where(
        Skill.status == STATUS_ACTIVE
    ).where(
        or_(
            Skill.scope == SCOPE_GLOBAL,
            (Skill.scope == SCOPE_PERSONAL) & (Skill.owner_id == user_id),
        )
    )
    return list(db.scalars(stmt))


def build_agent_skill_sources(db: Session, *, user_id) -> list[str]:
    """为 deepagents 的 create_deep_agent(skills=...) 构造 source 路径列表。

    返回技能 PARENT 目录的 MinIO 前缀列表，而非单个 skill 路径。
    deepagents 的 SkillsMiddleware 调用 backend.ls(source) 时期望
    source/ 下的**子目录**各为一个 skill（内含 SKILL.md），而非 source
    本身为 skill 目录。

    示例：skill minio_prefix = "skills/builtin/patent-de-ai/" 时，
    source = "skills/builtin/"（去掉末尾 skill 名），
    middleware 列出后找到 patent-de-ai/、patent-effect-contrast/ 等子目录。

    deepagents 语义：later source 覆盖 earlier（personal 后于 global，同名 personal 生效）。
    """
    skills = list_visible_skills(db, user_id=user_id)
    sources: list[str] = []
    seen: set[str] = set()
    # global 先（低优先级），personal 后（高优先级，覆盖同名 global）
    ordered = sorted(skills, key=lambda s: 0 if s.scope == SCOPE_GLOBAL else 1)
    for s in ordered:
        prefix = s.minio_prefix.rstrip("/")  # e.g. "skills/builtin/patent-de-ai"
        parts = prefix.split("/")
        if len(parts) >= 2:
            parent = "/".join(parts[:-1]) + "/"  # e.g. "skills/builtin/"
        else:
            parent = prefix + "/"
        if parent not in seen:
            seen.add(parent)
            sources.append(parent)
    return sources
