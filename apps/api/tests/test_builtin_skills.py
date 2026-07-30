# apps/api/tests/test_builtin_skills.py
"""内置 skill 加载器与不可编辑 guard 的测试。

覆盖：
- sync_builtin_skills 幂等同步（新建 / 更新 / 二次跑无重复）
- 跳过与非内置同名的 global skill（不覆盖 admin 手建）
- is_builtin 标记正确，scope=global/status=active 自动喂 agent
- service 层 update_skill / delete_skill 对 is_builtin=True 抛 ForbiddenError
- API 层 PUT/DELETE 对内置 skill 返回 403
"""
from pathlib import Path

import pytest

from app.models import Skill
from app.skills import service as skill_service
from app.skills.builtin_loader import BUILTIN_MINIO_PREFIX_ROOT, sync_builtin_skills


# ── 测试用 skill 目录 fixtures ──────────────────────────────────────────

_SKILL_MD_A = """\
---
name: builtin-alpha
description: 第一个测试内置技能
---

# Alpha 技能正文
做 A 的事情。
"""

_SKILL_MD_A_V2 = """\
---
name: builtin-alpha
description: 第一个测试内置技能（已更新描述）
---

# Alpha 技能正文
做 A 的事情，更新版。
"""

_SKILL_MD_B = """\
---
name: builtin-beta
description: 第二个测试内置技能
---

# Beta 技能正文
做 B 的事情。
"""


def _make_assets_dir(tmp_path: Path, skills: dict[str, str]) -> Path:
    """在 tmp_path/assets/skills/ 下按 {目录名: SKILL.md内容} 建测试 skill 目录。"""
    root = tmp_path / "assets" / "skills"
    for dirname, content in skills.items():
        d = root / dirname
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(content, encoding="utf-8")
    return root


# ── service 层：同步逻辑 ────────────────────────────────────────────────

def test_sync_creates_new_builtin_skills(db_session, monkeypatch, tmp_path):
    """首次同步：把文件系统的两个 skill 新建成 is_builtin=True 的 global active skill。"""
    root = _make_assets_dir(tmp_path, {"alpha": _SKILL_MD_A, "beta": _SKILL_MD_B})
    monkeypatch.setattr(
        "app.skills.builtin_loader._builtin_assets_root", lambda: root
    )

    created, updated = sync_builtin_skills(db_session)

    assert created == 2
    assert updated == 0
    skills = db_session.query(Skill).filter_by(is_builtin=True).all()
    assert {s.name for s in skills} == {"builtin-alpha", "builtin-beta"}
    for s in skills:
        assert s.scope == "global"
        assert s.status == "active"
        assert s.is_builtin is True
        assert s.minio_prefix.startswith(BUILTIN_MINIO_PREFIX_ROOT)


def test_sync_is_idempotent(db_session, monkeypatch, tmp_path):
    """二次同步：不重复创建，已有内置 skill 计为 updated。"""
    root = _make_assets_dir(tmp_path, {"alpha": _SKILL_MD_A})
    monkeypatch.setattr(
        "app.skills.builtin_loader._builtin_assets_root", lambda: root
    )

    sync_builtin_skills(db_session)  # 首次
    created, updated = sync_builtin_skills(db_session)  # 二次

    # 二次跑：无新建（created=0），已有的算更新（updated=1）
    assert created == 0
    assert updated == 1
    assert db_session.query(Skill).filter_by(is_builtin=True).count() == 1


def test_sync_updates_content(db_session, monkeypatch, tmp_path):
    """文件系统内容变化后同步：description 被刷新。"""
    root = _make_assets_dir(tmp_path, {"alpha": _SKILL_MD_A})
    monkeypatch.setattr(
        "app.skills.builtin_loader._builtin_assets_root", lambda: root
    )
    sync_builtin_skills(db_session)

    # 改文件内容（换 description）
    (root / "alpha" / "SKILL.md").write_text(_SKILL_MD_A_V2, encoding="utf-8")
    sync_builtin_skills(db_session)

    skill = db_session.query(Skill).filter_by(name="builtin-alpha").one()
    assert "已更新描述" in skill.description


def test_sync_skips_non_builtin_same_name(db_session, monkeypatch, tmp_path):
    """文件系统的内置 skill 与已存在的非内置同名 global skill 冲突时跳过，不覆盖。"""
    # 先建一个 admin 手建的同名 global skill（is_builtin=False）
    db_session.add(Skill(
        name="builtin-alpha", description="admin 手建的原描述",
        scope="global", status="active", minio_prefix="skills/global/builtin-alpha/",
        is_builtin=False,
    ))
    db_session.commit()

    root = _make_assets_dir(tmp_path, {"alpha": _SKILL_MD_A})
    monkeypatch.setattr(
        "app.skills.builtin_loader._builtin_assets_root", lambda: root
    )
    created, updated = sync_builtin_skills(db_session)

    assert created == 0
    assert updated == 0
    # 原 admin skill 未被覆盖
    skill = db_session.query(Skill).filter_by(name="builtin-alpha").one()
    assert skill.is_builtin is False
    assert skill.description == "admin 手建的原描述"


def test_sync_missing_dir_returns_empty(db_session, monkeypatch, tmp_path):
    """目录不存在时同步返回 (0,0)，不报错（启动降级语义）。"""
    monkeypatch.setattr(
        "app.skills.builtin_loader._builtin_assets_root",
        lambda: tmp_path / "nonexistent",
    )
    created, updated = sync_builtin_skills(db_session)
    assert (created, updated) == (0, 0)


# ── service 层：不可编辑 guard ──────────────────────────────────────────

def _make_builtin_skill(db_session, name="builtin-locked") -> Skill:
    """直接建一个 is_builtin=True 的 skill 行 + 写 MinIO SKILL.md（隔离 guard 逻辑）。

    必须写 MinIO：API 的 update 路径在调 update_skill 前，会先 read_skill_detail
    回读 SKILL.md（description-only 场景），缺 MinIO 内容会 404，干扰 guard 断言。
    conftest 的 _FAKE_STORAGE（autouse 单例）提供 put。
    """
    from app.core import storage as storage_mod
    from app.skills.service import assemble_skill_md, SKILL_MD_FILENAME

    s = Skill(
        name=name, description="内置不可改", scope="global", status="active",
        minio_prefix=f"{BUILTIN_MINIO_PREFIX_ROOT}{name}/", is_builtin=True,
    )
    db_session.add(s)
    db_session.commit()
    # 写 MinIO SKILL.md（让 read_skill_md 能读到）
    st = storage_mod.get_storage()
    st.put(
        "global", f"{s.minio_prefix}{SKILL_MD_FILENAME}",
        assemble_skill_md(name=name, description=s.description, body="内置正文").encode("utf-8"),
        "text/markdown",
    )
    return s


def test_update_builtin_skill_forbidden(db_session):
    """内置 skill 不允许 update（ForbiddenError）。"""
    from app.core.exceptions import ForbiddenError
    s = _make_builtin_skill(db_session)
    with pytest.raises(ForbiddenError):
        skill_service.update_skill(db_session, skill_id=s.id, description="改不了")


def test_delete_builtin_skill_forbidden(db_session):
    """内置 skill 不允许 delete（ForbiddenError）。"""
    from app.core.exceptions import ForbiddenError
    s = _make_builtin_skill(db_session)
    with pytest.raises(ForbiddenError):
        skill_service.delete_skill(db_session, skill_id=s.id)


# ── API 层：403 拦截 ────────────────────────────────────────────────────

def _login(client, registered_user):
    client.post("/api/v1/auth/login", json={
        "username": registered_user["username"],
        "password": registered_user["password"],
    })


def _make_admin(client, registered_user, db_session):
    from uuid import UUID
    from app.models import User
    user = db_session.query(User).filter_by(id=UUID(registered_user["id"])).first()
    user.role = "admin"
    db_session.commit()


def test_api_update_builtin_returns_403(client, registered_user, db_session):
    """admin 经 API 改内置 skill 返回 403。"""
    _make_admin(client, registered_user, db_session)
    _login(client, registered_user)
    s = _make_builtin_skill(db_session)

    resp = client.put(f"/api/v1/admin/skills/{s.id}", json={"description": "改不了"})
    assert resp.status_code == 403


def test_api_delete_builtin_returns_403(client, registered_user, db_session):
    """admin 经 API 删内置 skill 返回 403。"""
    _make_admin(client, registered_user, db_session)
    _login(client, registered_user)
    s = _make_builtin_skill(db_session)

    resp = client.delete(f"/api/v1/admin/skills/{s.id}")
    assert resp.status_code == 403


def test_admin_list_includes_builtin_flag(client, registered_user, db_session):
    """admin 列表返回的 skill 带 is_builtin 字段。"""
    _make_admin(client, registered_user, db_session)
    _login(client, registered_user)
    _make_builtin_skill(db_session)

    resp = client.get("/api/v1/admin/skills")
    assert resp.status_code == 200
    builtin = [s for s in resp.json() if s["is_builtin"]]
    assert len(builtin) == 1
    assert builtin[0]["name"] == "builtin-locked"
