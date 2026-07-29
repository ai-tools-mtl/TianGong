import uuid

from pgvector.sqlalchemy import HALFVEC as HalfVec
from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin

# 与 knowledge_chunk 对齐：bge-m3（统一 embedding 微服务）输出 1024 维
EMBEDDING_DIM = 1024

# 记忆来源（写路径区分）
SOURCE_AGENT = "agent"      # agent 在 loop 中自动写入
SOURCE_MANUAL = "manual"    # 用户在前端手动添加


class UserMemory(Base, IdMixin, TimestampMixin):
    """用户绑定的长期记忆（跨项目、跨会话稳定）。

    - user_id：严格隔离，仅本人可见、本人可检索（纯个人，无三域）。
    - content：一条记忆 = 一句话/一段话（建议 ≤200 字，前端校验）。
    - embedding：写入时同步生成；允许 NULL（embedding 配置不可用时降级为纯文本）。
    - source：区分 agent 自动写入 vs 用户手动添加。
    """
    __tablename__ = "user_memories"
    __table_args__ = (
        # 前端列表查询用：按用户 + 更新时间倒序。
        # 复合索引的 user_id 左前缀已覆盖 WHERE user_id=? 查询，无需单列索引。
        Index(
            "ix_user_memories_user_updated",
            "user_id", "updated_at",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    content: Mapped[str] = mapped_column(Text)
    embedding = mapped_column(HalfVec(EMBEDDING_DIM), nullable=True)
    source: Mapped[str] = mapped_column(String(20), default=SOURCE_AGENT)
