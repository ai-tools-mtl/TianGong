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
    """每测试用独立 sqlite 内存库。

    knowledge_chunks 用 pgvector Vector 类型,sqlite 不支持。
    解法:跳过原表,手动建一个「兼容版」(去掉 embedding 列,其余列齐全),
    让 service 层测试能真正写/改 chunk 的 scope/file_id/review_status——
    否则审核流等核心数据流只能被桩掉,测不到真实行为。
    """
    import sqlalchemy as sa

    eng = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # 排除原 knowledge_chunks(含 Vector 列,sqlite 建不了)
    tables = {
        name: t for name, t in Base.metadata.tables.items()
        if name != "knowledge_chunks"
    }
    for t in tables.values():
        t.create(eng, checkfirst=True)

    # knowledge_chunks 兼容版:与生产同名列。
    # embedding 用 JSON 替代 pgvector.Vector(SQLite 不支持)——测试不关心向量内容。
    kc_compat = sa.Table(
        "knowledge_chunks", sa.MetaData(),
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False, index=True),
        sa.Column("scope", sa.String(20), nullable=False),
        sa.Column("source_type", sa.String(30), nullable=False),
        sa.Column("source_id", sa.String(36), nullable=False, index=True),
        sa.Column("source_section_key", sa.String(50)),
        sa.Column("chunk_index", sa.Integer, default=0),
        sa.Column("content", sa.Text),
        sa.Column("tsv", sa.Text),  # PG 是 tsvector，SQLite 是 Text
        sa.Column("embedding", sa.JSON),
        sa.Column("metadata", sa.JSON),
        sa.Column("file_id", sa.String(36), index=True),
        sa.Column("review_status", sa.String(20)),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )
    kc_compat.create(eng, checkfirst=True)

    yield eng

    kc_compat.drop(eng, checkfirst=True)
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
    """注册一个普通用户，返回 {id, email, password}。

    直接构造 User 对象,不走 register 端点(不受邀请码约束)——
    给绝大多数只需要"一个已存在用户"的测试用。
    """
    u = User(
        username="testuser",
        email="test@example.com",
        password_hash=hash_password("Pass1234!"),
        name="测试用户",
    )
    db_session.add(u)
    db_session.commit()
    return {"id": str(u.id), "username": u.username, "email": u.email, "password": "Pass1234!"}


def make_invite_code(db_session, *, max_uses: int = 1) -> str:
    """测试 helper:生成一个有效邀请码,返回码字符串。

    供需要走 /auth/register 端点的测试用(内部产品化后注册需邀请码)。
    """
    from app.models import InviteCode
    import secrets
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    code = "".join(secrets.choice(alphabet) for _ in range(8))
    invite = InviteCode(code=code, max_uses=max_uses, used_count=0)
    db_session.add(invite)
    db_session.commit()
    return code
