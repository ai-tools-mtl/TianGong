import uuid

from sqlalchemy import Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ReviewLock(Base):
    """审查进行中互斥的 DB 行标记（跨进程/多 worker 可靠）。

    project_id 为主键：一个项目同一时刻最多一行锁。
    started_at / last_touch 为 epoch 秒（与 review_service 的 time.time() 语义
    一致，避免时区换算）。owner_token 标识本次占坑者——心跳/释放只作用于
    自己占的坑，防止 stale 抢占后原僵死进程回来误删/误续新持有者的锁。
    """

    __tablename__ = "review_locks"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    owner_token: Mapped[str] = mapped_column(String(36))
    started_at: Mapped[float] = mapped_column(Float)
    last_touch: Mapped[float] = mapped_column(Float)
