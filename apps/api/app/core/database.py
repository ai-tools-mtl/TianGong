from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

_settings = get_settings()
engine = create_engine(_settings.database_url, pool_pre_ping=True, future=True)
# expire_on_commit=False：commit 后不再 expire session 内所有 ORM 对象。
# 依据全量审计（89 处 commit）：44 处紧跟 db.refresh()（显式重查，免疫此配置），
# 其余多读客户端生成的 UUID 主键（commit 前已知）或 Python 端赋值字段。
# **唯一需注意**：读 server-default 列（如 created_at/updated_at 这类 DB 端赋值时间戳）
# 时，commit 后必须显式 db.refresh() 才能拿到 DB 生成的值——否则读到 None/旧值。
# 见 docs/superpowers/specs/2026-07-29-c1-expire-on-commit-design.md。
SessionLocal = sessionmaker(
    bind=engine, autoflush=False, autocommit=False, future=True,
    expire_on_commit=False,
)


def is_postgres() -> bool:
    """判断当前 engine 是否为 PostgreSQL（SQLite 测试库返回 False）。

    用于 G1 HNSW / G3 tsvector 等 PG-only 特性的方言判断。
    """
    return engine.dialect.name == 'postgresql'


def get_db() -> Generator[Session, None, None]:
    """FastAPI 依赖：每请求 yield 一个 session，结束自动关闭。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
