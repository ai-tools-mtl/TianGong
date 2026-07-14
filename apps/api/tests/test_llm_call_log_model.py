"""LLMCallLog 模型测试。"""

from app.models import Base, LLMCallLog


def test_llm_call_log_model_importable():
    """模型可从 app.models 导入。"""
    assert LLMCallLog is not None
    assert LLMCallLog.__tablename__ == "llm_call_logs"


def test_llm_call_log_create_row(db_session):
    """可插入一条记录，字段持久化（user_id/project_id 可空，无 FK 级联）。"""
    log = LLMCallLog(
        user_id=None,
        project_id=None,
        action="chat",
        model="glm-4-flash",
        provider="global",
        token_prompt=None,
        token_completion=None,
        duration_ms=123,
        status="success",
        error=None,
    )
    db_session.add(log)
    db_session.commit()
    db_session.refresh(log)

    assert log.id is not None
    assert log.action == "chat"
    assert log.duration_ms == 123
    assert log.status == "success"
    assert log.created_at is not None


def test_llm_call_log_has_no_content_fields():
    """设计 8.3 红线：模型绝不存 prompt/completion 内容字段。"""
    columns = {c.name for c in LLMCallLog.__table__.columns}
    assert "prompt" not in columns
    assert "completion" not in columns
    assert "content" not in columns
