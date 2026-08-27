"""HITL 决策审计测试（借鉴机制批次 C）。

核心契约：
1. 双事件：ask 落 pending、decide 翻新，悬挂行保持 pending；
2. 幂等：重复 decide 只动一次；非法决策值不放行；
3. **绝不进入模型上下文**——历史 dict/Message.meta 里的 HITL 字段在装配与
   压缩两条出口都必须消失（防模型学会迎合审批者，dsh approval 核心戒律）。
"""
import asyncio
import uuid

import pytest

from app.services.hitl_audit_service import (
    DECISION_APPROVE,
    DECISION_PENDING,
    DECISION_REJECT,
    record_ask,
    record_decision,
)


@pytest.fixture()
def turn_msg(db_session):
    """一条 user 消息作为 turn 锚点（hitl_decisions.message_id 外键目标）。"""
    from app.models import Conversation, Message, Project, Section

    project = Project(title="审计项目", user_id=uuid.uuid4())
    db_session.add(project)
    db_session.commit()
    section = Section(
        project_id=project.id, template_section_id="background",
        key="background", title="背景技术", order=1, content=None,
    )
    db_session.add(section)
    db_session.commit()
    conv = Conversation(
        section_id=section.id, kind="section", title="c", status="active",
    )
    db_session.add(conv)
    db_session.commit()
    msg = Message(section_id=section.id, conversation_id=conv.id,
                  role="user", content="画一下系统框图")
    db_session.add(msg)
    db_session.commit()
    return {"section": section, "conv": conv, "msg": msg}


def _ask_rows(db_session, msg_id):
    from sqlalchemy import select

    from app.models import HitlDecision
    return list(db_session.scalars(
        select(HitlDecision).where(HitlDecision.message_id == msg_id)
        .order_by(HitlDecision.created_at)
    ))


def test_record_ask_creates_pending_per_action(db_session, turn_msg):
    actions = [
        {"name": "generate_figure", "args": {}, "description": "d"},
        "bad-shape-entry",                        # 非 dict 容错 → unknown_tool
        {"args": {}},                             # 缺 name → unknown_tool
    ]
    record_ask(db_session, turn_message_id=turn_msg["msg"].id,
               section_id=turn_msg["section"].id, actions=actions)
    rows = _ask_rows(db_session, turn_msg["msg"].id)
    assert len(rows) == 3
    assert [r.decision for r in rows] == [DECISION_PENDING] * 3
    assert [r.tool_name for r in rows] == ["generate_figure", "unknown_tool", "unknown_tool"]


def test_suspended_ask_stays_pending_and_repeat_ask_keeps_history(db_session, turn_msg):
    msg_id = turn_msg["msg"].id
    record_ask(db_session, turn_message_id=msg_id,
               section_id=None, actions=[{"name": "generate_figure"}])
    # 用户从不回复（无 record_decision）→ 行保持 pending（悬挂即审计信号）
    assert all(r.decision == DECISION_PENDING for r in _ask_rows(db_session, msg_id))
    # 链式第二次询问：再插一行而非复用——完整保留询问史
    record_ask(db_session, turn_message_id=msg_id,
               section_id=None, actions=[{"name": "generate_figure"}])
    assert len(_ask_rows(db_session, msg_id)) == 2


def test_record_decision_updates_all_pending_then_idempotent(db_session, turn_msg):
    uid = uuid.uuid4()
    msg_id = turn_msg["msg"].id
    record_ask(db_session, turn_message_id=msg_id,
               section_id=None, actions=[{"name": "a"}, {"name": "b"}])
    n = record_decision(db_session, turn_message_id=msg_id,
                        decision=DECISION_REJECT, note="预算不足", decided_by=uid)
    assert n == 2
    rows = _ask_rows(db_session, msg_id)
    assert all(r.decision == DECISION_REJECT and r.decided_by == uid
               and r.decision_note == "预算不足" and r.decided_at is not None
               for r in rows)
    # 幂等：重复决策不再触碰已决行（decide 与 approve 语义均不产生新状态）
    assert record_decision(db_session, turn_message_id=msg_id,
                           decision=DECISION_APPROVE, note=None, decided_by=uid) == 0
    assert all(r.decision == DECISION_REJECT for r in _ask_rows(db_session, msg_id))


def test_record_decision_rejects_unknown_value(db_session, turn_msg):
    msg_id = turn_msg["msg"].id
    record_ask(db_session, turn_message_id=msg_id,
               section_id=None, actions=[{"name": "a"}])
    assert record_decision(db_session, turn_message_id=msg_id,
                           decision="edit", note=None, decided_by=None) == 0
    assert _ask_rows(db_session, msg_id)[0].decision == DECISION_PENDING


# ── 边界钉死：审计绝不进入模型上下文 ─────────────────────────────────────────

def test_compress_history_drops_hitl_fields():
    """压缩出口只输出 role/content——混进历史 dict 的 HITL 字段必须被丢弃。"""
    from app.ai.context_compactor import compress_history
    from app.services.llm_config_service import ResolvedChatConfig

    flagged = {
        "role": "assistant",
        "content": "好的，我来生成附图。",
        # 人为把 HITL 字段混进历史 dict（模拟有人错误地直灌 meta 的场景）
        "hitl_resolved": {"decision": DECISION_APPROVE},
        "pending_interrupt": [{"name": "generate_figure"}],
        "interrupted": True,
    }
    cfg = ResolvedChatConfig(base_url="http://x", api_key="k", model="m")
    out, snapshot = asyncio.run(compress_history([flagged], "继续", cfg))
    for m in out:
        assert set(m.keys()) <= {"role", "content"}, f"泄漏字段：{set(m.keys())}"
        assert "hitl_resolved" not in m and "pending_interrupt" not in m


def test_assemble_messages_drops_hitl_fields_from_history_content():
    """装配出口的历史回放同样只认 role/content——meta 属性不被读取。"""
    from types import SimpleNamespace

    from app.ai.context_assembler import assemble_messages

    section = SimpleNamespace(key="name", title="发明名称", status="empty")
    hist = [
        SimpleNamespace(role="user", content="q1"),
        SimpleNamespace(role="assistant", content="a1",
                        meta={"hitl_resolved": {"decision": DECISION_APPROVE},
                              "interrupted": True}),
    ]
    msgs = assemble_messages(section, hist, user_input="下一句")
    # 历史 assistant 消息的 content 原样回放；meta 中的任何键都不出现在消息体内
    assert msgs[-2].content == "a1"
    for m in msgs:
        blob = m.content if isinstance(m.content, str) else str(m.content)
        assert "hitl_resolved" not in blob and "pending_interrupt" not in blob
