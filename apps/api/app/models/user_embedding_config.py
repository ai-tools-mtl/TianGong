import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin


class UserEmbeddingConfig(Base, IdMixin, TimestampMixin):
    """用户的 embedding 配置（与 chat 配置独立——支持跨供应商混搭）。

    与 UserLLMConfig 对称：同样列结构，只是语义是 embedding 凭据。
    source 协议前缀 custom-emb:{id} 指向本表的行。
    """

    __tablename__ = "user_embedding_configs"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(50))  # 如「智谱 embedding」
    base_url: Mapped[str] = mapped_column(String(255))
    api_key_encrypted: Mapped[str] = mapped_column(String(512))
    model: Mapped[str] = mapped_column(String(100))  # embedding 模型名
