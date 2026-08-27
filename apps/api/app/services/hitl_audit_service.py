"""HITL 决策审计服务（借鉴机制批次 C）。

双事件写入：
- record_ask：interrupt 发生时每个待确认动作插一行 pending（created_at 即 ask 时间）。
  同一 turn 反复触发会留多行——完整保留询问史。
- record_decision：决策到达时把该 turn 全部 pending 行翻新为 approve/reject；
  只动 pending，重复调用幂等。无人回复的悬挂行保持 pending 即审计信号。

两处调用点都在 SSE 端点层（有 db 会话、与 partial 落库同事务边界）：
chat/resume 的 kind=="interrupt" 分支、resume 的决策透传前。
全部 fail-open：由调用方 try/except 包裹，审计失败不阻断对话。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import HitlDecision

DECISION_PENDING = "pending"
DECISION_APPROVE = "approve"
DECISION_REJECT = "reject"


def record_ask(db: Session, *, turn_message_id: uuid.UUID,
               section_id: uuid.UUID | None, actions: list[dict]) -> None:
    """interrupt 触发：每个待确认动作落一行 pending。actions 元素形如
    {"name": str, "args": ..., "description": str}（缺失容错）。"""
    for action in actions or []:
        name = action.get("name") if isinstance(action, dict) else None
        if not name or not isinstance(name, str):
            name = "unknown_tool"
        db.add(HitlDecision(
            message_id=turn_message_id,
            section_id=section_id,
            tool_name=name[:100],
            decision=DECISION_PENDING,
        ))
    db.commit()


def record_decision(db: Session, *, turn_message_id: uuid.UUID, decision: str,
                    note: str | None, decided_by: uuid.UUID | None) -> int:
    """决策落地：翻新该 turn 所有 pending 行。返回受影响行数（幂等：重复调用 0 行）。

    decision 已在端点侧白名单校验（approve/reject），此处不再放行其他值。
    """
    if decision not in (DECISION_APPROVE, DECISION_REJECT):
        return 0
    pending_ids = db.scalars(
        select(HitlDecision.id).where(
            HitlDecision.message_id == turn_message_id,
            HitlDecision.decision == DECISION_PENDING,
        )
    ).all()
    if not pending_ids:
        return 0
    result = db.execute(
        update(HitlDecision)
        .where(HitlDecision.id.in_(pending_ids))
        .values(
            decision=decision,
            decision_note=(note or None),
            decided_by=decided_by,
            decided_at=datetime.now(timezone.utc),
        )
    )
    db.commit()
    return result.rowcount or 0


def list_turn_decisions(db: Session, *, turn_message_id: uuid.UUID) -> list[HitlDecision]:
    """回读某 turn 的全部审计行（UI 徽标与后续 admin 查询共用）。"""
    return list(db.scalars(
        select(HitlDecision)
        .where(HitlDecision.message_id == turn_message_id)
        .order_by(HitlDecision.created_at)
    ))
