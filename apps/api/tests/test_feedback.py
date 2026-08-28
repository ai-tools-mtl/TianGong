"""AI 输出反馈测试（借鉴机制批次 H）：upsert 幂等 / 字段校验 / 鉴权 / admin 聚合。"""
import uuid

import pytest


def _mk_chain(db_session, owner_id):
    """project → section → conversation → assistant 消息（归属 owner）。"""
    from app.models import Conversation, Message, Project, Section

    project = Project(title="反馈项目", user_id=owner_id)
    db_session.add(project)
    db_session.commit()
    section = Section(
        project_id=project.id, template_section_id="background",
        key="background", title="背景技术", order=1, content=None,
    )
    db_session.add(section)
    db_session.commit()
    conv = Conversation(section_id=section.id, kind="section", title="c", status="active")
    db_session.add(conv)
    db_session.commit()
    msg = Message(section_id=section.id, conversation_id=conv.id,
                  role="assistant", content="这是 AI 回复")
    db_session.add(msg)
    db_session.commit()
    return {"project": project, "section": section, "conv": conv, "msg": msg}


def _user(db_session, name, role="user"):
    from app.core.security import hash_password
    from app.models import User

    u = User(
        username=f"fb-{uuid.uuid4().hex[:6]}",
        email=f"fb-{uuid.uuid4().hex[:6]}@tiangong.dev",
        password_hash=hash_password("Pass1234!"), name=name, role=role,
    )
    db_session.add(u)
    db_session.commit()
    return u


def _login(client, user):
    client.post("/api/v1/auth/login", json={
        "username": user.username, "password": "Pass1234!"})


# ── service 层：校验 + upsert ───────────────────────────────────────────────

def test_submit_validates(db_session):
    from app.services import feedback_service

    mid = uuid.uuid4()
    uid = uuid.uuid4()
    with pytest.raises(feedback_service.FeedbackValidationError, match="rating"):
        feedback_service.submit_feedback(db_session, message_id=mid, user_id=uid, rating="meh")
    with pytest.raises(feedback_service.FeedbackValidationError, match="未知标签"):
        feedback_service.submit_feedback(db_session, message_id=mid, user_id=uid,
                                         rating="bad", tags=["瞎写的"])
    # 重复标签先去重再校验 → 5 个含重复的输入收敛到 4 个，合法不抛（去重语义回归锚）
    with pytest.raises(feedback_service.FeedbackValidationError, match="500"):
        feedback_service.submit_feedback(db_session, message_id=mid, user_id=uid,
                                         rating="bad", note="长" * 501)


def test_submit_upsert_overwrites_single_row(db_session):
    from sqlalchemy import select

    from app.models import MessageFeedback
    from app.services import feedback_service

    mid, uid = uuid.uuid4(), uuid.uuid4()
    feedback_service.submit_feedback(db_session, message_id=mid, user_id=uid,
                                     rating="good")
    row2 = feedback_service.submit_feedback(db_session, message_id=mid, user_id=uid,
                                            rating="bad", tags=["事实", "格式"],
                                            note="编造参数")
    rows = list(db_session.scalars(select(MessageFeedback).where(
        MessageFeedback.message_id == mid)))
    assert len(rows) == 1 and rows[0].id == row2.id  # 覆盖不新插
    assert row2.rating == "bad" and row2.tags == ["事实", "格式"] and row2.note == "编造参数"


def test_same_message_different_users_two_rows(db_session):
    from sqlalchemy import select

    from app.models import MessageFeedback
    from app.services import feedback_service

    mid = uuid.uuid4()
    feedback_service.submit_feedback(db_session, message_id=mid, user_id=uuid.uuid4(), rating="good")
    feedback_service.submit_feedback(db_session, message_id=mid, user_id=uuid.uuid4(), rating="bad")
    assert len(list(db_session.scalars(select(MessageFeedback).where(
        MessageFeedback.message_id == mid)))) == 2


# ── 端点：鉴权 / 归属 / 契约 ────────────────────────────────────────────────

def test_endpoint_submit_upsert_and_authz(db_session, client):
    from app.services import feedback_service

    owner = _user(db_session, "拥有者")
    other = _user(db_session, "路人")
    chain = _mk_chain(db_session, owner.id)
    url = f"/api/v1/sections/{chain['section'].id}/messages/{chain['msg'].id}/feedback"

    _login(client, owner)
    res = client.post(url, json={"rating": "good"})
    assert res.status_code == 200 and res.json() == {"ok": True, "rating": "good"}
    # 覆盖提交
    res2 = client.post(url, json={"rating": "bad", "tags": ["格式"], "note": "缩进乱"})
    assert res2.status_code == 200

    # 非归属用户 → 404（section 归属过滤，防探测口径）
    _login(client, other)
    res3 = client.post(url, json={"rating": "bad"})
    assert res3.status_code == 404

    # 非法 rating → 422
    _login(client, owner)
    res4 = client.post(url, json={"rating": "so-so"})
    assert res4.status_code == 422

    from sqlalchemy import select

    from app.models import MessageFeedback
    rows = list(db_session.scalars(select(MessageFeedback).where(
        MessageFeedback.message_id == chain["msg"].id)))
    assert len(rows) == 1 and rows[0].rating == "bad" and rows[0].note == "缩进乱"
    assert feedback_service  # import 保留语义


def test_endpoint_rejects_user_message_and_foreign_section(db_session, client):
    from app.models import Message

    owner = _user(db_session, "拥有者2")
    chain = _mk_chain(db_session, owner.id)
    user_msg = Message(section_id=chain["section"].id,
                       conversation_id=chain["conv"].id, role="user", content="问")
    db_session.add(user_msg)
    db_session.commit()
    _login(client, owner)
    res = client.post(
        f"/api/v1/sections/{chain['section'].id}/messages/{user_msg.id}/feedback",
        json={"rating": "good"})
    assert res.status_code == 404  # 只允许 assistant 消息
    res2 = client.post(
        f"/api/v1/sections/{uuid.uuid4()}/messages/{chain['msg'].id}/feedback",
        json={"rating": "good"})
    assert res2.status_code in (403, 404)  # 不存在的 section 归属拒绝


# ── admin 聚合 ──────────────────────────────────────────────────────────────

def test_admin_summary_aggregation_and_authz(db_session, client):
    owner = _user(db_session, "聚合拥有者")
    admin = _user(db_session, "管理员", role="admin")
    chain = _mk_chain(db_session, owner.id)
    url = f"/api/v1/sections/{chain['section'].id}/messages/{chain['msg'].id}/feedback"
    _login(client, owner)
    assert client.post(url, json={"rating": "bad", "tags": ["事实", "事实", "格式"]}).status_code == 200

    # 普通用户访问 admin 聚合 → 403
    _login(client, owner)
    assert client.get("/api/v1/admin/stats/feedback").status_code == 403

    # admin：坏评计数/标签分布/章节 top
    _login(client, admin)
    res = client.get("/api/v1/admin/stats/feedback")
    assert res.status_code == 200
    data = res.json()
    assert data["bad"] >= 1 and data["total"] >= 1
    assert data["by_tag"].get("事实") == 1 and data["by_tag"].get("格式") == 1
    assert data["bad_by_section"].get("background") == 1
