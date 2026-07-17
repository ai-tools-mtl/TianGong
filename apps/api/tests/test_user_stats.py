"""用户聚合统计 API（Task 3.1）。

覆盖 GET /api/v1/admin/stats/users：
- 聚合统计正确（总数/活跃/禁用/新增/有效授权数）
- 非 admin → 403
- 红线：响应只含聚合数字，无私人字段
鉴权沿用 test_admin_api.py / test_grant_api.py 的 admin_and_login fixture。
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.core.security import hash_password
from app.models import User, UserGlobalLLMGrant


@pytest.fixture
def admin_and_login(client, db_session):
    """创建管理员并登录，返回 admin user。"""
    admin = User(
        username="admin",
        email="admin@example.com",
        password_hash=hash_password("Admin1234!"),
        name="管理员",
        role="admin",
        status="active",
        is_superuser=False,
    )
    db_session.add(admin)
    db_session.commit()
    client.post("/api/v1/auth/login", json={
        "username": "admin", "password": "Admin1234!",
    })
    return admin


def _make_user(db, username, *, status="active", created_at=None, role="user"):
    u = User(
        username=username,
        password_hash=hash_password("Pass1234!"),
        name=username,
        status=status,
        role=role,
    )
    if created_at:
        u.created_at = created_at
    db.add(u)
    return u


def test_user_stats_aggregation(client, db_session, admin_and_login):
    """聚合统计正确：总数/活跃/禁用/新增/有效授权数。

    鉴权：admin_and_login 已建一个 role=admin active 用户并登录。
    据此基线 + 我们插入的固定集合计算期望值，避免依赖 fixture 其他状态。
    """
    now = datetime.now(timezone.utc)
    old = now - timedelta(days=40)      # 超过 30 天
    within_30d = now - timedelta(days=15)  # 30d 内、7d 外
    within_7d = now - timedelta(days=3)    # 7d 内

    # 插入固定集合：2 active（1 新7d、1 新30d）+ 1 disabled（老）
    u_new7 = _make_user(db_session, "new7", status="active", created_at=within_7d)
    u_new30 = _make_user(db_session, "new30", status="active", created_at=within_30d)
    u_old_disabled = _make_user(db_session, "old_disabled", status="disabled", created_at=old)
    db_session.flush()  # 让 user.id（default=uuid4）生效，再建 grant

    # 有效授权：给 u_new7 授权（计入 granted_count）
    db_session.add(UserGlobalLLMGrant(user_id=u_new7.id))
    # 给 u_new30 授权再撤销（不计入 granted_count，但行存在用于审计）
    g_revoked = UserGlobalLLMGrant(user_id=u_new30.id)
    g_revoked.revoked_at = now
    db_session.add(g_revoked)
    db_session.commit()

    # 取响应前的基线快照（admin fixture + 我们插入的用户之外的状态不可控，故用 delta 断言）
    baseline_total = db_session.query(User).count()
    baseline_active = db_session.query(User).filter_by(status="active").count()
    baseline_disabled = db_session.query(User).filter_by(status="disabled").count()
    from sqlalchemy import func, select
    baseline_granted = int(db_session.scalar(
        select(func.count(UserGlobalLLMGrant.id)).where(UserGlobalLLMGrant.revoked_at.is_(None))
    ) or 0)

    resp = client.get("/api/v1/admin/stats/users")
    assert resp.status_code == 200
    data = resp.json()

    # 聚合数字精确等于 DB 当前状态
    assert data["total"] == baseline_total
    assert data["active"] == baseline_active
    assert data["disabled"] == baseline_disabled
    assert data["granted_count"] == baseline_granted

    # 我们插入的集合贡献：新增统计应包含刚插的 3 个（都 < now）
    # 用 >= 保证对 admin fixture 创建时间（同样很新）的鲁棒性
    assert data["new_7d"] >= 2   # u_new7 + u_new30? 不，u_new30 在 7d 外。至少 u_new7 + admin
    assert data["new_30d"] >= 3  # u_new7 + u_new30 + admin

    # granted_count 至少 1（u_new7 有效授权），且被撤销的不计入
    assert data["granted_count"] >= 1
    # 红线：响应不含任何私人字段
    for key in data:
        assert key in {"total", "active", "disabled", "new_7d", "new_30d", "granted_count"}, key


def test_user_stats_disabled_count(client, db_session, admin_and_login):
    """disabled 计数精确：插入的禁用用户被正确计入。"""
    baseline = client.get("/api/v1/admin/stats/users").json()
    baseline_disabled = baseline["disabled"]

    _make_user(db_session, "dis1", status="disabled")
    _make_user(db_session, "dis2", status="disabled")
    db_session.commit()

    data = client.get("/api/v1/admin/stats/users").json()
    assert data["disabled"] == baseline_disabled + 2


def test_user_stats_granted_excludes_revoked(client, db_session, admin_and_login):
    """granted_count 只计 revoked_at 为空的授权。"""
    _make_user(db_session, "g_active")
    u_revoke = _make_user(db_session, "g_revoke")
    db_session.commit()

    # 一条有效 + 一条已撤销
    db_session.add(UserGlobalLLMGrant(user_id=db_session.query(User).filter_by(username="g_active").one().id))
    revoked = UserGlobalLLMGrant(user_id=u_revoke.id)
    revoked.revoked_at = datetime.now(timezone.utc)
    db_session.add(revoked)
    db_session.commit()

    data = client.get("/api/v1/admin/stats/users").json()
    # 只有 1 条有效授权（g_active），g_revoke 已撤销不计
    assert data["granted_count"] == 1


def test_user_stats_normal_user_forbidden(client, registered_user):
    """非 admin 调统计端点 → 403。"""
    client.post("/api/v1/auth/login", json={
        "username": registered_user["username"], "password": registered_user["password"],
    })
    resp = client.get("/api/v1/admin/stats/users")
    assert resp.status_code == 403
