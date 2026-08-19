"""LangGraph Checkpointer 工厂/单例测试（附录 A 红利①基础）。

测试环境是 sqlite（conftest engine），is_pg=False → InMemorySaver；
fail-open：初始化异常降级 None，app 仍可用（符合 warning 模式偏好）。
"""

import asyncio
import sys

# 预热真实模块：_ainternal 在模块级对 AsyncConnectionPool 做下标求值，
# 必须在 monkeypatch 替换前完成导入，否则补丁类不可下标会炸在 import 上。
import langgraph.checkpoint.postgres.aio  # noqa: F401
import psycopg_pool  # noqa: F401
import pytest

from app.ai import checkpoint as ckpt_mod
from langgraph.checkpoint.memory import InMemorySaver

PG_URL = "postgresql+psycopg://u:p@localhost:5432/tiangong"


def _run_on_selector(coro):
    """pg 分支测试须跑在 SelectorEventLoop 上（Windows 默认 Proactor 会被守卫拦下）。

    loop_factory 参数 3.12+ 才有，低版本回退普通 run（非 Windows 平台本来就无 Proactor）。
    """
    try:
        asyncio.run(coro, loop_factory=asyncio.SelectorEventLoop)
    except TypeError:
        asyncio.run(coro)


def test_init_checkpointer_sqlite_uses_inmemory():
    """is_pg=False（sqlite/测试）→ InMemorySaver（进程内，非持久化）。"""
    asyncio.run(ckpt_mod.init_checkpointer("sqlite://", is_pg=False))
    assert isinstance(ckpt_mod.get_checkpointer(), InMemorySaver)


def test_init_checkpointer_failopen(monkeypatch):
    """初始化异常 → _checkpointer=None，不抛（fail-open，app 仍启动）。"""
    def boom(*a, **kw):
        raise RuntimeError("simulated init failure")
    # 替换 checkpoint 模块已 import 的 InMemorySaver，让 is_pg=False 分支也抛异常
    monkeypatch.setattr("app.ai.checkpoint.InMemorySaver", boom)
    asyncio.run(ckpt_mod.init_checkpointer("sqlite://", is_pg=False))
    assert ckpt_mod.get_checkpointer() is None


def test_get_checkpointer_singleton():
    """多次 get 返回同一实例（进程级单例）。"""
    asyncio.run(ckpt_mod.init_checkpointer("sqlite://", is_pg=False))
    a = ckpt_mod.get_checkpointer()
    b = ckpt_mod.get_checkpointer()
    assert a is b


def test_init_checkpointer_pg_strips_dialect_suffix(monkeypatch):
    """is_pg=True 时 SQLAlchemy 方言 URL 须剥掉 +driver 后缀再喂 psycopg。

    回归：postgresql+psycopg:// 直接传入 AsyncConnectionPool 会导致 conninfo
    解析必败（missing "="），pool 永远连不上、启动降级无持久化。
    """
    captured = {}

    class FakePool:
        def __init__(self, **kw):
            captured["conninfo"] = kw["conninfo"]
            captured["connect_kwargs"] = kw.get("kwargs")
            captured["closed"] = False

        async def open(self):
            pass

        async def close(self):
            captured["closed"] = True

    class FakeSaver:
        async def setup(self):
            pass

    monkeypatch.setattr("psycopg_pool.AsyncConnectionPool", FakePool)
    monkeypatch.setattr("langgraph.checkpoint.postgres.aio.AsyncPostgresSaver", lambda **kw: FakeSaver())

    _run_on_selector(ckpt_mod.init_checkpointer(PG_URL, is_pg=True))
    assert captured["conninfo"] == "postgresql://u:p@localhost:5432/tiangong"
    # 对齐官方 from_conn_string：autocommit（CONCURRENTLY 建索引硬要求）+ dict_row（按列名取值）
    assert captured["connect_kwargs"]["autocommit"] is True
    assert captured["connect_kwargs"]["prepare_threshold"] == 0
    assert isinstance(ckpt_mod.get_checkpointer(), FakeSaver)
    assert captured["closed"] is False


def test_init_checkpointer_pg_closes_pool_on_failure(monkeypatch):
    """pg 分支 setup 失败 → fail-open 降级 None，且 pool 被关闭。

    回归：不关池的话 psycopg_pool 后台 worker 持失败配置无限重试，
    WARNING 持续刷屏（startup 日志噪音根因之一）。
    """
    pools = []

    class FakePool:
        def __init__(self, **kw):
            self.closed = False
            pools.append(self)

        async def open(self):
            pass

        async def close(self):
            self.closed = True

    class BoomSaver:
        async def setup(self):
            raise RuntimeError("db down")

    monkeypatch.setattr("psycopg_pool.AsyncConnectionPool", FakePool)
    monkeypatch.setattr("langgraph.checkpoint.postgres.aio.AsyncPostgresSaver", lambda **kw: BoomSaver())

    _run_on_selector(ckpt_mod.init_checkpointer(PG_URL, is_pg=True))
    assert ckpt_mod.get_checkpointer() is None
    assert pools and pools[0].closed is True


@pytest.mark.skipif(sys.platform != "win32", reason="仅 Windows 有 ProactorEventLoop")
def test_init_checkpointer_pg_proactor_guard(monkeypatch):
    """Windows + ProactorEventLoop → 提前降级，不建池、不等 30s 超时。

    psycopg 异步在 Proactor 上连接必败；守卫让 fail-open 即刻发生并给出可行动原因。
    """
    def boom(*a, **kw):
        raise AssertionError("Proactor 场景不应创建 pool")

    monkeypatch.setattr("psycopg_pool.AsyncConnectionPool", boom)
    # 默认 asyncio.run 即 Proactor（win32），无需特设
    asyncio.run(ckpt_mod.init_checkpointer(PG_URL, is_pg=True))
    assert ckpt_mod.get_checkpointer() is None
