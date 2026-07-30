# apps/api/app/skills/builtin_loader.py
"""内置 skill 加载器：从项目根 assets/skills/ 启动时同步进系统。

内置 skill = 由代码仓库管理的 global skill，与 admin 在 UI 手建的 skill 区分：
- 标记 is_builtin=True，UI 禁用编辑/删除（内容由文件系统管理，重启重载）。
- 独立 minio_prefix skills/builtin/{name}/，避免与 admin 的 skills/global/{name}/ 碰撞。
- scope=global, status=active —— 直接进 build_agent_skill_sources 的可见集合，
  无需改动 agent / visibility 逻辑。

同步语义（幂等 upsert）：
- 文件系统有、DB 无            → 新建（写 MinIO + 建 DB 行）
- 文件系统有、DB 有且 is_builtin → 更新内容（重写 MinIO，刷 description）
- 文件系统有、DB 有但非内置同名 → 跳过并 warning（不覆盖 admin/用户手建的同名 skill）
- 文件系统无、DB 有且 is_builtin → 本轮不自动删（避免误删；见模块 docstring 末尾）

解析逻辑复用 zip_import：SKILL.md 的 frontmatter 解析、name 校验、文件分桶
（scripts/references/assets）与 zip 导入完全一致，保证内置与上传的 skill 同构。

路径解析：assets/skills/ 位于仓库根（apps/api 往上三级）。容器部署时该目录需
随镜像打入（Dockerfile 拷贝），本地开发直接命中。
"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

import loguru

from app.core import storage as _storage_mod
from app.models.skill import SCOPE_GLOBAL, STATUS_ACTIVE, Skill
from app.skills.service import _bucket_for_scope, write_skill_directory
from app.skills.zip_import import (
    ParsedSkill,
    _classify_file,
    _parse_frontmatter,
    _validate_name,
)

# 内置 skill 在 MinIO 中的目录前缀根（区别于 admin 手建的 skills/global/）
BUILTIN_MINIO_PREFIX_ROOT = "skills/builtin/"

# 必须存在的 SKILL.md 文件名（与 service.SKILL_MD_FILENAME 一致）
_SKILL_MD = "SKILL.md"


def _builtin_assets_root() -> Path:
    """返回仓库根下的 assets/skills/ 目录。

    本文件位于 <repo>/apps/api/app/skills/builtin_loader.py，
    parents[4] = <repo>（apps/api 往上三级到仓库根）。
    """
    # parents: [0]=skills [1]=app [2]=api [3]=apps [4]=<repo>
    repo_root = Path(__file__).resolve().parents[4]
    return repo_root / "assets" / "skills"


def _parse_skill_dir(skill_dir: Path) -> ParsedSkill | None:
    """解析单个 skill 目录（含 SKILL.md + 可选 scripts/references/assets）。

    复用 zip_import 的解析逻辑，与 zip 导入同构。目录缺 SKILL.md 或解析失败
    返回 None（调用方决定跳过还是告警）。
    """
    skill_md_path = skill_dir / _SKILL_MD
    if not skill_md_path.is_file():
        return None

    skill_md_content = skill_md_path.read_text(encoding="utf-8")
    # 复用 zip_import 的 frontmatter 解析 + name 校验
    name, description, body = _parse_frontmatter(skill_md_content)
    name = _validate_name(name)

    parsed = ParsedSkill(name=name, description=description, body=body)

    # 遍历目录其余文件，按扩展名分桶（与 zip 导入 _classify_file 一致）
    for path in sorted(skill_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.name == _SKILL_MD and path.parent == skill_dir:
            continue  # 跳过根 SKILL.md（已解析）
        rel = path.relative_to(skill_dir).as_posix()  # 统一正斜杠
        data = path.read_bytes()
        bucket, value = _classify_file(rel, data)
        # 文件名取 basename（扁平化，与 zip 导入一致）
        fname = rel.rsplit("/", 1)[-1]
        if bucket == "scripts":
            parsed.scripts[fname] = value  # type: ignore[assignment]
        elif bucket == "references":
            parsed.references[fname] = value  # type: ignore[assignment]
        else:
            parsed.assets[fname] = value  # type: ignore[assignment]

    return parsed


def scan_builtin_skills(root: Path) -> list[ParsedSkill]:
    """扫描 assets/skills/ 下所有子目录，返回解析成功的 ParsedSkill 列表。

    每个直接子目录视为一个 skill（目录名即 skill 名空间）。缺 SKILL.md 或
    解析失败的目录跳过并 warning，不中断整体同步。
    """
    if not root.is_dir():
        loguru.logger.warning(f"内置 skill 目录不存在，跳过同步：{root}")
        return []

    results: list[ParsedSkill] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue  # 跳过散落文件，只认目录式 skill
        parsed = _parse_skill_dir(entry)
        if parsed is None:
            loguru.logger.warning(
                f"内置 skill 目录「{entry.name}」缺少 SKILL.md，跳过"
            )
            continue
        try:
            results.append(parsed)
        except Exception as e:  # noqa: BLE001 — 单个 skill 解析失败不阻塞其余
            loguru.logger.exception(
                f"内置 skill「{entry.name}」解析失败，跳过：{e}"
            )
    return results


def sync_builtin_skills(db: Session) -> tuple[int, int]:
    """启动时同步内置 skill：扫描文件系统 → 幂等 upsert 进 DB + MinIO。

    Returns:
        (created, updated) —— 本次新建数与更新数，供日志输出。
    """
    root = _builtin_assets_root()
    parsed_list = scan_builtin_skills(root)

    created = 0
    updated = 0
    bucket = _bucket_for_scope(SCOPE_GLOBAL)

    for parsed in parsed_list:
        # 按 name 查现有 skill（内置 skill 走 global 档，owner_id=NULL）
        existing = db.scalar(
            select(Skill).where(
                Skill.scope == SCOPE_GLOBAL,
                Skill.owner_id.is_(None),
                Skill.name == parsed.name,
            )
        )

        prefix = f"{BUILTIN_MINIO_PREFIX_ROOT}{parsed.name}/"

        if existing is None:
            # 新建：先写 MinIO 目录，再建 DB 行
            write_skill_directory(
                bucket=bucket, prefix=prefix,
                name=parsed.name, description=parsed.description, body=parsed.body,
                scripts=parsed.scripts, references=parsed.references, assets=parsed.assets,
            )
            skill = Skill(
                name=parsed.name, description=parsed.description,
                scope=SCOPE_GLOBAL, owner_id=None, status=STATUS_ACTIVE,
                minio_prefix=prefix, is_builtin=True,
            )
            db.add(skill)
            db.commit()
            db.refresh(skill)
            created += 1
            loguru.logger.info(f"内置 skill 新建：{parsed.name}")
        elif existing.is_builtin:
            # 更新：重写 MinIO 内容 + 刷 description（name/minio_prefix 不变）
            write_skill_directory(
                bucket=bucket, prefix=existing.minio_prefix,
                name=parsed.name, description=parsed.description, body=parsed.body,
                scripts=parsed.scripts, references=parsed.references, assets=parsed.assets,
            )
            existing.description = parsed.description
            existing.status = STATUS_ACTIVE  # 内置始终 active
            db.commit()
            db.refresh(existing)
            updated += 1
            loguru.logger.info(f"内置 skill 更新：{parsed.name}")
        else:
            # 非 builtin 同名（admin/用户手建）—— 不覆盖，告警
            loguru.logger.warning(
                f"内置 skill「{parsed.name}」与已存在的非内置 global skill 同名，"
                f"跳过（不覆盖用户数据）"
            )

    # 孤儿清理：DB 中 is_builtin=True 但文件系统已无对应目录的 skill，
    # 本轮不做自动删除（避免误删，且重载语义下用户应感知）。如需清理可后续加
    # admin「重新同步」入口显式处理。
    _orphan_warning(db, parsed_list)

    return created, updated


def _orphan_warning(db: Session, parsed_list: list[ParsedSkill]) -> None:
    """检测 DB 中已无文件系统对应目录的内置 skill，输出 warning（不删除）。"""
    builtin_in_db = db.scalars(
        select(Skill).where(Skill.scope == SCOPE_GLOBAL, Skill.is_builtin.is_(True))
    ).all()
    names_on_disk = {p.name for p in parsed_list}
    for skill in builtin_in_db:
        if skill.name not in names_on_disk:
            loguru.logger.warning(
                f"内置 skill「{skill.name}」在文件系统中已不存在，"
                f"但 DB 仍保留（未自动删除；如需移除请手动处理或恢复目录）"
            )


def get_builtin_skill_names(db: Session) -> list[str]:
    """返回当前 DB 中所有内置 skill 的 name（供诊断/测试）。"""
    rows = db.scalars(
        select(Skill.name).where(Skill.is_builtin.is_(True))
    ).all()
    return list(rows)
