import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import hash_password
from app.models import Base, User


@pytest.fixture(autouse=True)
def _clear_cookie_domain(monkeypatch):
    """测试环境清空 cookie domain，避免 TestClient 跨域 cookie 拒收。"""
    settings = get_settings()
    monkeypatch.setattr(settings, "cookie_domain", "")


@pytest.fixture(scope="function")
def engine():
    """每测试用独立 sqlite 内存库。knowledge_chunks 用 pgvector，sqlite 不支持，跳过。"""
    eng = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # 排除 knowledge_chunks（Vector 类型 sqlite 不支持）
    tables = {
        name: t for name, t in Base.metadata.tables.items()
        if name != "knowledge_chunks"
    }
    for t in tables.values():
        t.create(eng, checkfirst=True)
    yield eng
    for t in reversed(list(tables.values())):
        t.drop(eng, checkfirst=True)
    eng.dispose()


@pytest.fixture
def db_session(engine):
    """直接操作的 session（service 层测试用）。"""
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def app_obj(engine):
    """构造 app，override get_db 指向测试库。"""
    TestingSession = sessionmaker(bind=engine)

    def override_get_db():
        session = TestingSession()
        try:
            yield session
        finally:
            session.close()

    from app.main import app
    app.dependency_overrides[get_db] = override_get_db
    yield app
    app.dependency_overrides.clear()


@pytest.fixture
def client(app_obj):
    with TestClient(app_obj) as c:
        yield c


@pytest.fixture
def registered_user(db_session) -> dict:
    """注册一个普通用户，返回 {id, email, password}。"""
    u = User(
        email="test@example.com",
        password_hash=hash_password("Pass1234!"),
        name="测试用户",
    )
    db_session.add(u)
    db_session.commit()
    return {"id": str(u.id), "email": u.email, "password": "Pass1234!"}
