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


def test_template_defaults():
    from app.models import Template
    db = _session()
    t = Template(name="测试模板", structure=[])
    db.add(t)
    db.flush()
    assert t.is_default is False
    assert t.is_system is False


def test_section_defaults():
    from app.models import Section
    db = _session()
    u = User(email="s@b.com", password_hash="x", name="S")
    db.add(u)
    db.flush()
    p = Project(user_id=u.id, title="P")
    db.add(p)
    db.flush()
    s = Section(project_id=p.id, template_section_id="ts1", order=1, key="name", title="发明名称")
    db.add(s)
    db.flush()
    assert s.status == "empty"
    assert s.content is None


def test_parse_job_defaults():
    from app.models import ParseJob
    db = _session()
    u = User(email="pj@b.com", password_hash="x", name="PJ")
    db.add(u)
    db.flush()
    job = ParseJob(user_id=u.id, source_path="/tmp/test.docx")
    db.add(job)
    db.flush()
    assert job.status == "pending"
    assert job.template_id is None


def test_section_has_version_field_default_1(db_session):
    """Section.version 默认 1（乐观锁基线）。"""
    from app.models import Project, Section
    # 字段定义存在
    s = Section(
        project_id=None, template_section_id="t1", order=1, key="name",
        title="发明名称", status="empty",
    )
    assert hasattr(s, "version")
    # Python 端 default 在 flush/INSERT 时生效：需父级 project 以满足外键约束
    u = User(email="v@b.com", password_hash="x", name="V")
    db_session.add(u)
    db_session.flush()
    p = Project(user_id=u.id, title="P")
    db_session.add(p)
    db_session.flush()
    s.project_id = p.id
    db_session.add(s)
    db_session.flush()
    assert s.version == 1
