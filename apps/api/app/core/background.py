"""统一异步后台任务 spawn 入口。

供 FastAPI BackgroundTasks 之外的场景使用(如 startup 恢复扫描)。
max_workers=4 防止孤儿任务洪水把进程跑爆。

设计:docs/superpowers/specs/2026-07-27-firecrawl-web-ingestion-design.md 第 5 节。
"""

import time
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Callable

from app.core.logging import get_logger

logger = get_logger(__name__)

_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="bg-task")


def _log_task_outcome(future: Future, timing: dict) -> None:
    """done callback：任务异常必落日志。

    线程池 Future 的异常若无人取，会静默吞掉——解析/向量化/归档后台任务
    挂了后台一个字都没有，只能靠用户报障才发现。这里统一兜底记日志。
    """
    duration_ms = timing.get("duration_ms")
    duration_note = f" | {duration_ms:.0f}ms" if duration_ms is not None else ""
    try:
        future.result()
        logger.debug(f"后台任务完成{duration_note}")
    except Exception:
        logger.exception(f"后台任务异常{duration_note}")


def spawn_background_task(func: Callable, *args, **kwargs) -> Future:
    """提交异步任务到线程池。立即返回 Future,不阻塞调用方。"""
    _start = time.perf_counter()
    _timing: dict = {}  # 闭包持有，worker 与 done callback 共享（future 可能晚于 worker 完成才可用）

    def _run():
        try:
            return func(*args, **kwargs)
        finally:
            _timing["duration_ms"] = (time.perf_counter() - _start) * 1000

    logger.debug(f"后台任务提交：{getattr(func, '__qualname__', func)}")
    future = _executor.submit(_run)
    future.add_done_callback(lambda f: _log_task_outcome(f, _timing))
    return future
