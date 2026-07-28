"""用户长期记忆服务：CRUD + embedding 生成 + 语义检索 + 去重。"""
import uuid as _uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError, ValidationError
from app.models import UserMemory

# 记忆来源常量（与 model 对齐）
SOURCE_AGENT = "agent"
SOURCE_MANUAL = "manual"

# 检索默认参数
DEFAULT_TOP_K = 5
SIMILARITY_THRESHOLD = 0.5  # 与 rag/retriever.py 一致

# 去重阈值：embedding 余弦相似度 ≥ 此值视为重复，触发合并而非新增
DEDUP_SIMILARITY = 0.85


def _try_embed(db: Session, user_id, text: str) -> list[float] | None:
    """尝试生成 embedding。配置不可用或失败时返回 None（降级为纯文本）。

    复用用户的 embedding 配置链路（resolve_embedding_config），与知识库检索同源。
    """
    from app.rag.embedding import embed_text
    from app.services.llm_config_service import resolve_embedding_config

    embed_config = resolve_embedding_config(db, user_id=user_id)
    if embed_config is None:
        return None
    try:
        return embed_text(text, embed_config=embed_config)
    except Exception:
        return None


def create_memory(
    db: Session, *, user_id, content: str, source: str = SOURCE_AGENT
) -> UserMemory:
    """创建一条记忆。自动生成 embedding（失败降级 NULL）。"""
    if not content or not content.strip():
        raise ValidationError("记忆内容不能为空")
    embedding = _try_embed(db, user_id, content)
    memory = UserMemory(
        user_id=user_id,
        content=content.strip(),
        embedding=embedding,
        source=source,
    )
    db.add(memory)
    db.flush()
    return memory


def list_memories(
    db: Session, *, user_id, source: str | None = None, limit: int = 200
) -> list[UserMemory]:
    """列出用户所有记忆，按 updated_at 倒序。"""
    stmt = select(UserMemory).where(UserMemory.user_id == user_id)
    if source:
        stmt = stmt.where(UserMemory.source == source)
    stmt = stmt.order_by(UserMemory.updated_at.desc()).limit(limit)
    return list(db.scalars(stmt))


def update_memory(db: Session, *, memory_id, user_id, content: str) -> UserMemory:
    """更新记忆内容，重新生成 embedding。"""
    mem = db.get(UserMemory, memory_id)
    if mem is None or mem.user_id != user_id:
        raise NotFoundError("记忆不存在")
    if not content.strip():
        raise ValidationError("记忆内容不能为空")
    mem.content = content.strip()
    mem.embedding = _try_embed(db, user_id, content.strip())
    db.flush()
    return mem


def delete_memory(db: Session, *, memory_id, user_id) -> None:
    """删除记忆（仅本人，否则 NotFoundError 不泄露存在性）。"""
    mem = db.get(UserMemory, memory_id)
    if mem is None or mem.user_id != user_id:
        raise NotFoundError("记忆不存在")
    db.delete(mem)
    db.flush()
