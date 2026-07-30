"""用户长期记忆服务：CRUD + embedding 生成 + 语义检索 + 去重。"""
import uuid as _uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.database import is_postgres
from app.core.exceptions import NotFoundError, ValidationError
from app.models import UserMemory
from app.models.user_memory import SOURCE_AGENT, SOURCE_MANUAL

# 检索默认参数
DEFAULT_TOP_K = 5
SIMILARITY_THRESHOLD = 0.5  # 与 rag/retriever.py 一致

# 去重阈值：embedding 余弦相似度 ≥ 此值视为重复，触发合并而非新增
DEDUP_SIMILARITY = 0.85

# 【v1.1】热度/淘汰参数（从 settings 读，默认值见 config.py）
from app.core.config import get_settings

_settings = get_settings()
HALF_LIFE_DAYS = _settings.memory_half_life_days
MEMORY_LIMIT = _settings.memory_limit
GRACE_DAYS = _settings.memory_grace_days


def _decay(delta_seconds: float) -> float:
    """指数衰减。Δt=0 返回 1.0；半衰期(HALF_LIFE_DAYS 天)后腰斩到 0.5。"""
    days = delta_seconds / 86400
    return 0.5 ** (days / HALF_LIFE_DAYS)


def _compute_hot_score(mem, now: datetime) -> float:
    """实时计算热度分。

    score = (hit_count + 1) × decay(now - last_hit_at)
    - hit_count+1：避免零乘 + 冷启动公平（新记忆不天生垫底）
    - last_hit_at IS NULL（新记忆）：Δt=0 → decay=1.0（满分，不被淘汰）
    """
    hit = mem.hit_count or 0
    last = mem.last_hit_at or now  # NULL 视为「刚命中」，得满分衰减
    delta = (now - last).total_seconds()
    return (hit + 1) * _decay(delta)


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
    _enforce_capacity(db, user_id=user_id)   # 【v1.1】写入后即时淘汰
    return memory


def _enforce_capacity(db: Session, *, user_id) -> None:
    """写入后检查容量，超限则淘汰最冷的一条。

    豁免：GRACE_DAYS 天内的新记忆（last_hit_at IS NULL 或距今 < GRACE_DAYS）不参与淘汰，
    防止刚写入即被删。

    双列近似排序（hit_count ASC, last_hit_at ASC）的单调性与
    (hit_count+1)×decay(Δt) 一致——热度最低 = 命中数最少 + 最久未触达。
    只删一条（每次写入最多 +1，删 1 即恢复上限）。
    全部在豁免期时暂不处理（MVP 200 条规模下概率极低）。
    """
    count = db.scalar(
        select(func.count()).select_from(UserMemory)
        .where(UserMemory.user_id == user_id)
    )
    if count <= MEMORY_LIMIT:
        return

    grace_cutoff = datetime.now(timezone.utc) - timedelta(days=GRACE_DAYS)
    coldest = db.scalars(
        select(UserMemory)
        .where(
            (UserMemory.user_id == user_id)
            & (UserMemory.last_hit_at.isnot(None))
            & (UserMemory.last_hit_at < grace_cutoff)
        )
        .order_by(UserMemory.hit_count.asc(), UserMemory.last_hit_at.asc())
        .limit(1)
    ).first()

    if coldest is not None:
        db.delete(coldest)
        db.flush()


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
    """更新记忆内容，重新生成 embedding。

    embed 失败时保留旧 embedding（而非置空）——避免 embed 服务临时抖动
    导致原有 embedding 丢失、记忆从此检索不到（静默数据降级）。
    content 已更新，旧 embedding 虽不精确但仍可近似召回，优于完全检索不到。
    """
    mem = db.get(UserMemory, memory_id)
    if mem is None or mem.user_id != user_id:
        raise NotFoundError("记忆不存在")
    if not content.strip():
        raise ValidationError("记忆内容不能为空")
    mem.content = content.strip()
    new_emb = _try_embed(db, user_id, content.strip())
    if new_emb is not None:
        mem.embedding = new_emb
    # new_emb is None 时保留旧 embedding（见 docstring）
    db.flush()
    return mem


def delete_memory(db: Session, *, memory_id, user_id) -> None:
    """删除记忆（仅本人，否则 NotFoundError 不泄露存在性）。"""
    mem = db.get(UserMemory, memory_id)
    if mem is None or mem.user_id != user_id:
        raise NotFoundError("记忆不存在")
    db.delete(mem)
    db.flush()


@dataclass
class MemorySearchResult:
    content: str
    score: float
    id: _uuid.UUID


def search_memories(
    db: Session, *, user_id, query: str, top_k: int = DEFAULT_TOP_K
) -> list[MemorySearchResult]:
    """语义检索用户的记忆（读路径核心）。

    返回按相似度排序的 Top-K 记忆。embedding 配置不可用或 query 向量化失败时返回
    空列表（降级，与 create/update/dedup 同走 _try_embed）。

    实现镜像 rag/retriever.py：cosine_distance + HNSW ef_search +
    similarity 阈值过滤。pgvector 仅在 PostgreSQL 生效，SQLite 无法执行该查询。
    """
    # query 向量化复用 _try_embed（与写入路径同源，统一降级语义，便于测试）。
    query_vec = _try_embed(db, user_id, query)
    if query_vec is None:
        return []

    # G1：HNSW 索引的动态探测参数，随 top_k 放大保证召回率（仅 PG 生效，SQLite 静默忽略）。
    # 注意：SET 不支持参数绑定（psycopg3 会编译成 $1 占位符，PG 拒绝），
    # 必须 int() 后字面拼接。ef 是内部算的整数，非用户输入，无注入风险。
    if is_postgres():
        ef = max(40, top_k * 4)
        db.execute(text(f"SET LOCAL hnsw.ef_search = {int(ef)}"))

    stmt = (
        select(
            UserMemory,
            UserMemory.embedding.cosine_distance(query_vec).label("distance"),
        )
        .where(
            (UserMemory.user_id == user_id)
            & (UserMemory.embedding.isnot(None))
        )
        .order_by("distance")
        .limit(top_k)
    )
    rows = db.execute(stmt).all()

    results = []
    for mem, distance in rows:
        score = 1.0 - distance
        # 防御：cosine_distance 正常范围 [0,2]，零向量/异常向量可能返回 NaN。
        # NaN 无法与阈值比较（NaN < x 恒为 False），会绕过过滤被注入 prompt。
        # 用 distance 范围判断更稳（score=NaN 时 distance 也是 NaN，!= distance 自身）。
        if distance != distance:  # NaN 检测（NaN != NaN）
            continue
        if distance < 0 or distance > 2:  # 超出 cosine_distance 合理范围
            continue
        if score < SIMILARITY_THRESHOLD:
            continue
        results.append(MemorySearchResult(content=mem.content, score=score, id=mem.id))
    return results


def find_similar_memory(
    db: Session, *, user_id, content: str, threshold: float = DEDUP_SIMILARITY
) -> UserMemory | None:
    """查找与 content 高度相似的已有记忆（写路径去重用）。

    返回相似度 ≥ threshold 的最近一条。无相似或 embedding 不可用时返回 None。
    """
    embedding = _try_embed(db, user_id, content)
    if embedding is None:
        return None

    # 与 search_memories 对齐：显式 SET ef_search，避免 HNSW 默认 ef=40 在
    # 记忆量增大后漏召回最相似项 → 去重失效 → 产生近似重复记忆。
    # 去重只需 top1，ef=40 足够（search_memories 用 max(40, top_k*4) 是为多结果召回）。
    if is_postgres():
        db.execute(text("SET LOCAL hnsw.ef_search = 40"))

    stmt = (
        select(
            UserMemory,
            UserMemory.embedding.cosine_distance(embedding).label("distance"),
        )
        .where(
            (UserMemory.user_id == user_id)
            & (UserMemory.embedding.isnot(None))
        )
        .order_by("distance")
        .limit(1)
    )
    row = db.execute(stmt).first()
    if row is None:
        return None
    mem, distance = row
    if (1.0 - distance) >= threshold:
        return mem
    return None
