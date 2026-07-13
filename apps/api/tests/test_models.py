from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Base, User, Project, SystemSetting


def _session():
    """内存 sqlite session，验证模型与 DB 集成的默认值。"""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_user_defaults():
    db = _session()
    u = User(email="a@b.com", password_hash="x", name="A")
    db.add(u)
    db.flush()  # 触发 DB 层默认值
    assert u.role == "user"
    assert u.status == "active"
    assert u.org_id is None
    assert u.is_superuser is False


def test_project_stage_defaults_to_disclosure():
    db = _session()
    u = User(email="a@b.com", password_hash="x", name="A")
    db.add(u)
    db.flush()
    p = Project(user_id=u.id, title="我的发明", template_id=None)
    db.add(p)
    db.flush()
    assert p.stage == "disclosure"
    assert p.status == "draft"
    assert p.progress_pct == 0


def test_system_setting_key_value():
    db = _session()
    s = SystemSetting(key="llm_global_enabled", value={"enabled": True})
    db.add(s)
    db.flush()
    assert s.key == "llm_global_enabled"
    assert s.value == {"enabled": True}
