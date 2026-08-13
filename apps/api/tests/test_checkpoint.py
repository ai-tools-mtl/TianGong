"""LangGraph Checkpointer 工厂/单例测试（附录 A 红利①基础）。

测试环境是 sqlite（conftest engine），is_pg=False → InMemorySaver；
fail-open：初始化异常降级 None，app 仍可用（符合 warning 模式偏好）。
"""

import asyncio

from app.ai import checkpoint as ckpt_mod
from langgraph.checkpoint.memory import InMemorySaver


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
