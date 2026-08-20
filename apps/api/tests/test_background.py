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


def test_spawn_task_exception_is_logged(monkeypatch):
    """任务抛异常：done callback 落 error 日志（异常不再静默吞掉）。"""
    captured = {}

    class _FakeLogger:
        def debug(self, msg, *a, **kw):
            pass

        def exception(self, msg, *a, **kw):
            captured["exception"] = msg

    import app.core.background as bg
    monkeypatch.setattr(bg, "logger", _FakeLogger())

    def boom():
        raise RuntimeError("worker exploded")

    fut = spawn_background_task(boom)
    # result 会重抛异常；等待任务执行完即可
    try:
        fut.result(timeout=2)
    except RuntimeError:
        pass

    import time as _t
    _t.sleep(0.05)  # done callback 异步于 result() 执行
    assert "后台任务异常" in captured.get("exception", "")


def test_spawn_task_success_no_error_log(monkeypatch):
    """任务成功：不打异常日志。"""
    captured = {}

    class _FakeLogger:
        def debug(self, msg, *a, **kw):
            pass

        def exception(self, msg, *a, **kw):
            captured["exception"] = msg

    import app.core.background as bg
    monkeypatch.setattr(bg, "logger", _FakeLogger())

    fut = spawn_background_task(lambda: 42)
    assert fut.result(timeout=2) == 42

    import time as _t
    _t.sleep(0.05)
    assert "exception" not in captured
