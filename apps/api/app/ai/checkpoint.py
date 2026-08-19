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

import asyncio
import re
import sys
from contextlib import suppress
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
            from psycopg.rows import dict_row
            from psycopg_pool import AsyncConnectionPool

            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

            # psycopg 异步不支持 Windows ProactorEventLoop（连接必败且要白等 30s 超时）。
            # 提前探测立即降级：uvicorn --reload/多 worker 在 win32 用 SelectorEventLoop 可用，
            # 单进程裸跑（Proactor）则降级无持久化，warning 给出可行动原因。
            if sys.platform == "win32" and isinstance(
                asyncio.get_running_loop(), asyncio.ProactorEventLoop
            ):
                raise RuntimeError(
                    "Windows 下当前事件循环是 ProactorEventLoop，psycopg 异步不可用"
                    "（改用 uvicorn --reload 或 --workers >1 可切到 SelectorEventLoop）"
                )

            # psycopg 只认 postgresql:// URI 或 key=value conninfo，
            # SQLAlchemy 方言 URL（postgresql+psycopg://...）直接传入解析必败，
            # 表现为 pool 每次重试报 missing "=" 且永远连不上。
            conninfo = re.sub(r"^postgresql\+[^:]+://", "postgresql://", database_url)

            # 连接参数对齐官方 from_conn_string（3.x 版已是单连接上下文管理器，
            # 进程级单例须自建 pool）：autocommit 是 setup() 迁移里的
            # CREATE INDEX CONCURRENTLY 的硬要求（不能跑在事务块内）；
            # dict_row 因 saver 查询按列名取值；prepare_threshold=0 禁预编译缓存。
            pool = AsyncConnectionPool(
                conninfo=conninfo,
                open=False,
                kwargs={
                    "autocommit": True,
                    "prepare_threshold": 0,
                    "row_factory": dict_row,
                },
            )
            try:
                await pool.open()
                saver = AsyncPostgresSaver(conn=pool)
                await saver.setup()
                _checkpointer = saver
            except Exception:
                # 失败必须关池：不关的话 pool 后台 worker 持失败配置无限重试，
                # 即使 fail-open 降级后 WARNING 也会持续刷屏。
                with suppress(Exception):
                    await pool.close()
                raise
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


async def close_checkpointer() -> None:
    """app shutdown 调用：关闭 AsyncPostgresSaver 持有的 pool。

    saver.conn 可能是 pool（本项目用法）或单连接（from_conn_string 用法），两者
    都有 async close()。不关的话进程退出阶段 pool 后台 worker 挂着活连接，
    轻则拖慢优雅停机，重则（脚本/CLI 场景）卡死事件循环收尾。
    """
    global _checkpointer
    cp, _checkpointer = _checkpointer, None
    conn = getattr(cp, "conn", None)  # InMemorySaver 无 conn，getattr 兜 None
    if conn is not None:
        with suppress(Exception):
            await conn.close()
