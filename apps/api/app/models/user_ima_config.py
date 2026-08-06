import uuid

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin


class UserIMAConfig(Base, IdMixin, TimestampMixin):
    """用户的腾讯 ima 检索源凭据（单配置：user_id 唯一）。

    用于把 ima 知识库作为「实时外部检索源」——对话预检索时本地 RAG 与 ima search
    并行，合并片段拼进 system prompt。不落库，纯实时检索。

    与 UserLLMConfig 的差异：ima 是单账号单源，一个用户只存一条配置，
    无多配置 CRUD；通过 enabled 开关控制是否参与检索。
    """

    __tablename__ = "user_ima_configs"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True,
    )  # unique：单配置语义，一个用户一条
    name: Mapped[str] = mapped_column(String(50), default="我的 ima")
    client_id_encrypted: Mapped[str] = mapped_column(String(512))
    api_key_encrypted: Mapped[str] = mapped_column(String(512))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
