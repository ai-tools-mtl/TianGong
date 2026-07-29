import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, func, Text, TypeDecorator
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# 生产用 JSONB，sqlite 测试降级为 JSON（详见 GOTCHAS G2）
JSONType = JSONB().with_variant(JSON, "sqlite")


class TSVectorType(TypeDecorator):
    """跨方言 tsvector 类型。

    PG 端用原生 tsvector（G3 BM25 召回列）；SQLite 测试库降级为 Text 占位
    （无 to_tsvector，tsv 逻辑在 service 层 is_postgres 守卫下跳过）。
    修预先存在的 bug：原模型把 tsv 声明为 Text，PG INSERT 时 ::VARCHAR cast
    与 tsvector 列类型不匹配（DatatypeMismatch）。用 TSVECTOR 让 cast 对齐。
    """
    impl = Text
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(TSVECTOR())
        return dialect.type_descriptor(Text())


class Base(DeclarativeBase):
    pass


class IdMixin:
    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
