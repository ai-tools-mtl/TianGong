# apps/api/tests/test_docker_runner.py
"""Docker sandbox runner 测试。

不真实起容器（CI 无 Docker），mock docker SDK 的 client.containers.run。
测试：拉 MinIO 脚本 → 注入容器 → 执行 → 回收。
"""


def test_execute_script_success(monkeypatch):
    """execute_script 构造正确的 docker run 命令（受限参数）。"""
    from app.sandbox import docker_runner

    captured = {}

    class _FakeContainer:
        def __init__(self, **kw):
            captured["kwargs"] = kw
        def put_archive(self, path, stream):
            captured["archive_path"] = path
        def wait(self, timeout=None):
            return {"StatusCode": 0}
        def logs(self):
            return b"output result"
        def remove(self, force):
            captured["removed"] = force

    class _FakeContainers:
        def run(self, image, command, **kw):
            captured["image"] = image
            captured["command"] = command
            return _FakeContainer(**kw)

    class _FakeDockerClient:
        containers = _FakeContainers()

    monkeypatch.setattr(docker_runner, "_get_docker_client", lambda: _FakeDockerClient())

    result = docker_runner.execute_script(
        script_content="print('hello')",
        language="python",
        timeout=10,
    )
    assert result["status"] == "success"
    assert "output result" in result["output"]
    # 安全约束：无网络
    assert captured["kwargs"].get("network_mode") == "none"
    # 只读 rootfs
    assert captured["kwargs"].get("read_only") is True
    # 内存限制
    assert "256m" in str(captured["kwargs"].get("mem_limit", ""))
    # 容器被清理
    assert captured.get("removed") is True


def test_execute_script_timeout(monkeypatch):
    """超时返回 failed。"""
    from app.sandbox import docker_runner

    class _FakeContainer:
        def put_archive(self, path, stream): pass
        def wait(self, timeout=None):
            raise Exception("timeout: container did not respond")
        def kill(self): pass
        def logs(self): return b""
        def remove(self, force): pass
    class _FakeContainers:
        def run(self, *a, **kw): return _FakeContainer()
    class _FakeDockerClient:
        containers = _FakeContainers()

    monkeypatch.setattr(docker_runner, "_get_docker_client", lambda: _FakeDockerClient())
    result = docker_runner.execute_script(
        script_content="while True: pass", language="python", timeout=1,
    )
    assert result["status"] == "failed"
    assert "超时" in result["error"] or "timeout" in result["error"].lower()


def test_execute_script_nonzero_exit(monkeypatch):
    """非零退出码返回 failed。"""
    from app.sandbox import docker_runner

    class _FakeContainer:
        def put_archive(self, path, stream): pass
        def wait(self, timeout=None): return {"StatusCode": 1}
        def logs(self): return b"Traceback: error"
        def remove(self, force): pass
    class _FakeContainers:
        def run(self, *a, **kw): return _FakeContainer()
    class _FakeDockerClient:
        containers = _FakeContainers()

    monkeypatch.setattr(docker_runner, "_get_docker_client", lambda: _FakeDockerClient())
    result = docker_runner.execute_script(
        script_content="raise Exception()", language="python", timeout=10,
    )
    assert result["status"] == "failed"
    assert "1" in result["error"]


def test_execute_script_unsupported_language():
    """不支持的语言返回 failed。"""
    from app.sandbox.docker_runner import execute_script
    result = execute_script(script_content="x", language="ruby", timeout=10)
    assert result["status"] == "failed"
    assert "ruby" in result["error"]


def test_pull_script_from_minio(monkeypatch):
    """从 MinIO 拉脚本内容。"""
    from app.sandbox import docker_runner
    from app.core import storage as storage_mod

    fake = {("global", "skills/g/s/scripts/foo.py"): b"print('hi')"}

    class _FakeStorage:
        def get(self, b, k): return fake.get((b, k), b"")
        def stat(self, b, k): return (b, k) in fake

    monkeypatch.setattr(storage_mod, "get_storage", lambda: _FakeStorage())

    content = docker_runner.pull_script_from_minio(
        bucket="global", key="skills/g/s/scripts/foo.py",
    )
    assert content == b"print('hi')"


def test_docker_unavailable_returns_error(monkeypatch):
    """Docker daemon 不可用时返回明确错误（不崩）。"""
    from app.sandbox import docker_runner

    def _raise():
        raise ConnectionError("docker daemon not running")
    monkeypatch.setattr(docker_runner, "_get_docker_client", _raise)

    result = docker_runner.execute_script(
        script_content="print('x')", language="python", timeout=10,
    )
    assert result["status"] == "failed"
    assert "docker" in result["error"].lower() or "daemon" in result["error"].lower()
