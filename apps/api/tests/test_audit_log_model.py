"""AuditLog 模型测试。"""

from app.models import AuditLog, Base


def test_audit_log_model_importable():
    assert AuditLog is not None
    assert AuditLog.__tablename__ == "audit_logs"


def test_audit_log_create_row(db_session):
    """可插入审计记录，detail 为 JSON dict。"""
    log = AuditLog(
        actor_id=None,  # 测试中先不绑用户，验证字段可空写入
        actor_email="admin@example.com",
        action="set_global_llm",
        target_type="system_setting",
        target_id="llm_global_config",
        detail={"model": "glm-4-flash", "base_url": "https://x", "enabled": True},
    )
    db_session.add(log)
    db_session.commit()
    db_session.refresh(log)

    assert log.id is not None
    assert log.action == "set_global_llm"
    assert log.detail["model"] == "glm-4-flash"
    # 关键：detail 中绝无 api_key
    assert "api_key" not in log.detail
    assert log.created_at is not None
