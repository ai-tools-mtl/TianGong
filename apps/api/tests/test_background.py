"""线程池后台任务 spawn 测试。"""

import time

from app.core.background import spawn_background_task


def test_spawn_executes_function():
    """spawn 的任务被执行。"""
    result = {"done": False}

    def worker():
        time.sleep(0.01)
        result["done"] = True

    fut = spawn_background_task(worker)
    fut.result(timeout=2)  # 等完成

    assert result["done"] is True


def test_spawn_passes_args():
    """参数被正确传递。"""
    result = {}

    def worker(a, b, c=0):
        result["args"] = (a, b, c)

    fut = spawn_background_task(worker, 1, 2, c=3)
    fut.result(timeout=2)

    assert result["args"] == (1, 2, 3)


def test_spawn_does_not_block_caller():
    """spawn 立即返回,不阻塞调用方。"""
    result = {"started": False}

    def slow_worker():
        result["started"] = True
        time.sleep(1)

    start = time.monotonic()
    spawn_background_task(slow_worker)
    elapsed = time.monotonic() - start

    assert elapsed < 0.5  # 立即返回
