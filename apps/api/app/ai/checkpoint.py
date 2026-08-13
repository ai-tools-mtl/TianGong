"""LangGraph Checkpointer 进程级单例（设计 §13.3 / 附录 A 红利①：Checkpoint）。

Postgres → AsyncPostgresSaver（agent loop 中间态落库，为后续 resume/HITL 打基础）；
非 Postgres（测试/sqlite）→ InMemorySaver（进程内，不持久化）。
fail-open：初始化失败降级 None，app 仍启动——checkpoint 是增强非核心
（符合用户 warning 模式偏好，见 feedback-security-warning-mode）。

双真源约定（设计核心）：
- messages 表 = canonical（用户可见历史、请求开始时 history 重建源）
- checkpoint = transient（单 turn agent loop 中间态，仅记录不回放）
history 重建逻辑完全不变，checkpoint 只持久化 agent 内部进度。
"""

from logging import getLogger

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver

logger = getLogger(__name__)

_checkpointer: BaseCheckpointSaver | None = None


async def init_checkpointer(database_url: str, *, is_pg: bool) -> None:
    """app startup 调一次，初始化进程级 checkpointer 单例。

    Postgres: AsyncPostgresSaver + 独立 AsyncConnectionPool（不复用 SQLAlchemy sync engine），
    setup() 建 4 张 checkpoint 表（DDL 幂等，非 Alembic，不进迁移链）。
    fail-open：任何异常 warning 后置 None，agent 不 checkpoint 但功能不受影响。
    """
    global _checkpointer
    try:
        if is_pg:
            from psycopg_pool import AsyncConnectionPool

            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

            pool = AsyncConnectionPool(conninfo=database_url, open=False)
            await pool.open()
            saver = AsyncPostgresSaver(conn=pool)
            await saver.setup()
            _checkpointer = saver
            logger.info("LangGraph Checkpointer 已启用（AsyncPostgresSaver，持久化）")
        else:
            _checkpointer = InMemorySaver()
            logger.info("LangGraph Checkpointer 已启用（InMemorySaver，非持久化）")
    except Exception as e:
        logger.warning(f"Checkpointer 初始化失败，降级无持久化: {e}")
        _checkpointer = None


def get_checkpointer() -> BaseCheckpointSaver | None:
    """返回单例；未初始化或 fail-open 后为 None（agent 跳过 checkpoint，功能不受影响）。"""
    return _checkpointer
