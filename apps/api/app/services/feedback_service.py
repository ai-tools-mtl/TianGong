"""AI 输出反馈服务（借鉴机制批次 H）。

submit：鉴权与归属由端点层做（section 归属 + assistant 角色），本层只管
字段校验与 upsert。summary：admin 聚合（好坏比 / 标签分布 / 坏评按章节 top）。
"""
from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import MessageFeedback
from app.models.message_feedback import ALLOWED_FEEDBACK_TAGS  # noqa: F401  (再导出)


class FeedbackValidationError(ValueError):
    """字段非法（rating/tags/note）——端点层转 422。"""


def submit_feedback(
    db: Session, *, message_id: uuid.UUID, user_id: uuid.UUID,
    rating: str, tags: list[str] | None = None, note: str | None = None,
) -> MessageFeedback:
    """校验 + upsert（同人同消息覆盖）。"""
    if rating not in ("good", "bad"):
        raise FeedbackValidationError("rating 仅支持 good / bad")
    tags = [t for t in (tags or []) if t]
    # 单次提交内去重（保序）——重复勾选同一标签不应放大聚合计数
    tags = list(dict.fromkeys(tags))
    if len(tags) > 4:
        raise FeedbackValidationError("标签最多 4 个")
    for t in tags:
        if t not in ALLOWED_FEEDBACK_TAGS:
            raise FeedbackValidationError(f"未知标签：{t}")
    if note is not None and len(note) > 500:
        raise FeedbackValidationError("备注最长 500 字")

    row = db.scalar(select(MessageFeedback).where(
        MessageFeedback.message_id == message_id,
        MessageFeedback.user_id == user_id,
    ))
    if row is None:
        row = MessageFeedback(message_id=message_id, user_id=user_id)
        db.add(row)
    row.rating = rating
    row.tags = tags or None
    row.note = (note or None)
    db.commit()
    return row


def get_feedback_summary(db: Session, *, days: int = 30) -> dict:
    """admin 聚合：好坏计数、标签分布、坏评按章节类型 top（近 N 天）。"""
    from datetime import datetime, timedelta, timezone

    since = datetime.now(timezone.utc) - timedelta(days=days)

    base = (
        select(MessageFeedback.rating, func.count(MessageFeedback.id))
        .where(MessageFeedback.created_at >= since)
        .group_by(MessageFeedback.rating)
    )
    counts = {"good": 0, "bad": 0}
    for rating, n in db.execute(base):
        counts[rating] = int(n)

    # 标签分布（JSON 数组成员计数：双方言通用做法——Python 侧聚合，量级小）
    tag_rows = db.scalars(select(MessageFeedback.tags).where(
        MessageFeedback.created_at >= since,
        MessageFeedback.tags.isnot(None),
    )).all()
    by_tag: dict[str, int] = {}
    for tags in tag_rows:
        for t in tags or []:
            by_tag[t] = by_tag.get(t, 0) + 1

    # 坏评按章节 key 聚合 top（join messages → sections 取 key）
    from app.models import Message, Section

    bad_by_section: dict[str, int] = {}
    rows = db.execute(
        select(Section.key, func.count(MessageFeedback.id))
        .select_from(MessageFeedback)
        .join(Message, Message.id == MessageFeedback.message_id)
        .join(Section, Section.id == Message.section_id)
        .where(MessageFeedback.created_at >= since,
               MessageFeedback.rating == "bad")
        .group_by(Section.key)
    ).all()
    for key, n in rows:
        bad_by_section[key] = int(n)

    total = counts["good"] + counts["bad"]
    return {
        "days": days,
        "good": counts["good"],
        "bad": counts["bad"],
        "total": total,
        "good_ratio": round(counts["good"] / total, 3) if total else None,
        "by_tag": dict(sorted(by_tag.items(), key=lambda kv: -kv[1])),
        "bad_by_section": dict(sorted(bad_by_section.items(), key=lambda kv: -kv[1])),
    }
