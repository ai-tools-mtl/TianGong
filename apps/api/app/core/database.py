from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

_settings = get_settings()
engine = create_engine(_settings.database_url, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


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
