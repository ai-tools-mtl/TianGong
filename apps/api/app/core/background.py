"""统一异步后台任务 spawn 入口。

供 FastAPI BackgroundTasks 之外的场景使用(如 startup 恢复扫描)。
max_workers=4 防止孤儿任务洪水把进程跑爆。

设计:docs/superpowers/specs/2026-07-27-firecrawl-web-ingestion-design.md 第 5 节。
"""

from concurrent.futures import Future, ThreadPoolExecutor
from typing import Callable

_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="bg-task")


def spawn_background_task(func: Callable, *args, **kwargs) -> Future:
    """提交异步任务到线程池。立即返回 Future,不阻塞调用方。"""
    return _executor.submit(func, *args, **kwargs)
