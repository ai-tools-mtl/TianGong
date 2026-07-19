"""审查记录越权访问防护（断链 B1 修复，设计 13.1）。

GET /api/v1/projects/{project_id}/reviews 原本不做项目归属校验，
任何已认证用户枚举 project_id 即可读取他人审查记录（评分、证据、建议）。

设计 13.1：越权返回 404（防探测），而非 403 或空列表 200。
"""

import uuid

from app.core.security import hash_password
from app.models import ReviewRecord, User
from app.services import project_service as ps
from app.services.seed_service import ensure_default_template


# ── 辅助 ──

def _make_user(db, username, name):
    u = User(
        username=username,
        email=f"{username}@tiangong.dev",
        password_hash=hash_password("Pass1234!"),
        name=name,
    )
    db.add(u)
    db.commit()
    return u


def _login(client, username, password="Pass1234!"):
    """复用 test_collaboration.py 的登录模式，cookie 设到 client 上。"""
    res = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    assert res.status_code == 200, res.text


def _make_review_record(db, project, user, *, score=80, round_=1):
    """直接落一条审查记录，绕开 review_service 的 LLM 依赖。"""
    rec = ReviewRecord(
        project_id=project.id,
        user_id=user.id,
        rubric_snapshot=[{"id": "c1", "weight": 100}],
        round=round_,
        total_score=score,
        previous_score=None,
        dimension_scores=[{"id": "c1", "score": score}],
        resolved_issues=[],
        remaining_issues=[],
    )
    db.add(rec)
    db.commit()
    return rec


# ── 越权（红线）──

def test_list_reviews_other_user_returns_404(client, db_session):
    """用户 B 访问用户 A 的项目审查记录 → 404（防探测，非 200 空列表 / 非 403）。

    即使 A 的项目下「有数据」，B 也应得到 404——这才是 13.1 的语义：
    不让攻击者通过响应差异探测「该项目是否存在 + 是否有审查记录」。
    """
    ensure_default_template(db_session)

    # 用户 A 建项目并落一条审查记录
    a = _make_user(db_session, "alice", "Alice")
    project = ps.create_project(db_session, user=a, title="A 的项目")
    _make_review_record(db_session, project, a, score=88)

    # 用户 B 登录后访问 A 的项目
    _make_user(db_session, "bob", "Bob")
    _login(client, "bob")

    resp = client.get(f"/api/v1/projects/{project.id}/reviews")
    assert resp.status_code == 404, (resp.status_code, resp.text)
    # 不得泄露 A 的任何审查数据
    assert resp.json()["code"] == "not_found"


def test_list_reviews_nonexistent_project_returns_404(client, db_session, registered_user):
    """访问不存在的 project_id → 404（不可探测）。"""
    _login(client, registered_user["username"])

    resp = client.get(f"/api/v1/projects/{uuid.uuid4()}/reviews")
    assert resp.status_code == 404, resp.status_code


# ── 正常路径（owner）──

def test_list_reviews_owner_returns_200(client, db_session):
    """项目 owner 访问自己的审查记录 → 200，返回完整记录。"""
    ensure_default_template(db_session)

    owner = _make_user(db_session, "carol", "Carol")
    project = ps.create_project(db_session, user=owner, title="Carol 的项目")
    rec = _make_review_record(db_session, project, owner, score=92)

    _login(client, "carol")

    resp = client.get(f"/api/v1/projects/{project.id}/reviews")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body) == 1
    assert body[0]["total_score"] == 92
    assert body[0]["round"] == 1
    assert body[0]["id"] == str(rec.id)
