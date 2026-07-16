import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.core import storage as _storage_mod  # 测试启动即注入 fake storage 单例
from app.core.database import get_db
from app.core.security import hash_password
from app.models import Base, User


class _FakeStorage:
    """内存 dict 模拟 minio(关键约束 5:测试也走 storage 接口,不恢复 local)。

    模块级单例:BackgroundTask 在响应返回后执行(monkeypatch 已还原),
    必须用永久注入的单例才能让后台任务读到请求存的对象。
    """

    def __init__(self):
        self._data: dict[tuple[str, str], bytes] = {}

    def put(self, bucket: str, key: str, content: bytes, content_type: str) -> None:
        self._data[(bucket, key)] = content

    def get(self, bucket: str, key: str) -> bytes:
        return self._data.get((bucket, key), b"")

    def delete(self, bucket: str, key: str) -> None:
        self._data.pop((bucket, key), None)

    def stat(self, bucket: str, key: str) -> bool:
        return (bucket, key) in self._data

    def copy(self, src_bucket: str, src_key: str, dst_bucket: str, dst_key: str) -> None:
        self._data[(dst_bucket, dst_key)] = self._data.get((src_bucket, src_key), b"")

    def reset(self) -> None:
        self._data.clear()


# 永久注入(非 monkeypatch):conftest 加载即替换工厂,
# BackgroundTask 跨边界执行时仍拿到同一个 fake 实例。
_FAKE_STORAGE = _FakeStorage()
_storage_mod._storage_singleton = _FAKE_STORAGE
_storage_mod.get_storage = lambda: _FAKE_STORAGE  # type: ignore[assignment]


@pytest.fixture(autouse=True)
def _reset_storage():
    """每测试清空 fake storage 数据,保证测试间隔离。"""
    _FAKE_STORAGE.reset()


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
