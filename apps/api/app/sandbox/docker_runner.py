# apps/api/app/sandbox/docker_runner.py
"""Docker sandbox：隔离容器执行用户脚本（spec Q12-b）。

安全约束（spec Q15-A 直读 MinIO）：
- network_mode="none"：无网络访问
- read_only=True：rootfs 只读（/tmp 除外，用 tmpfs）
- mem_limit + cpu_quota：资源上限
- timeout：超时 kill
执行前从 MinIO 拉脚本注入容器 /tmp。
"""
import io
import tarfile

from loguru import logger

# 受限镜像：官方 python slim
_DEFAULT_IMAGE = "python:3.11-slim"
_MEM_LIMIT = "256m"
_CPUS = 0.5


def _get_docker_client():
    """懒加载 docker client。Docker 不可用时抛异常。"""
    import docker
    return docker.from_env()


def pull_script_from_minio(*, bucket: str, key: str) -> bytes:
    """从 MinIO 拉脚本内容（spec Q15-A：sandbox 直读 MinIO）。"""
    from app.core import storage as _storage_mod
    st = _storage_mod.get_storage()
    return st.get(bucket, key)


def execute_script(
    *, script_content: bytes | str, language: str = "python",
    timeout: int = 30, image: str | None = None,
) -> dict:
    """在隔离 Docker 容器中执行脚本。

    Returns:
        {"status": "success"|"failed", "output": str, "error": str|None}
    """
    if isinstance(script_content, bytes):
        script_bytes = script_content
    else:
        script_bytes = script_content.encode("utf-8")

    # 语言映射
    if language == "python":
        fname = "script.py"
        command = ["python", "/tmp/script.py"]
    elif language == "bash":
        fname = "script.sh"
        command = ["bash", "/tmp/script.sh"]
    else:
        return {"status": "failed", "output": "", "error": f"不支持的语言：{language}"}

    img = image or _DEFAULT_IMAGE

    # 获取 docker client（不可用时明确报错）
    try:
        client = _get_docker_client()
    except Exception as e:
        return {
            "status": "failed", "output": "",
            "error": f"Docker daemon 不可用：{e}。请确保 Docker 已启动。",
        }

    container = None
    try:
        container = client.containers.run(
            img,
            command=command,
            detach=True,
            network_mode="none",      # 无网络
            read_only=True,           # rootfs 只读
            mem_limit=_MEM_LIMIT,
            cpu_quota=int(_CPUS * 100000),  # 0.5 CPU
            working_dir="/tmp",
            tmpfs={"/tmp": "size=16m"},  # /tmp 可写（tmpfs）
            stdin_open=True,
        )
        # 把脚本通过 tar archive 注入容器 /tmp
        tar_stream = io.BytesIO()
        with tarfile.open(fileobj=tar_stream, mode="w") as tar:
            info = tarfile.TarInfo(name=f"/tmp/{fname}")
            info.size = len(script_bytes)
            tar.addfile(info, io.BytesIO(script_bytes))
        tar_stream.seek(0)
        container.put_archive("/", tar_stream)

        result = container.wait(timeout=timeout)
        exit_code = result.get("StatusCode", -1)
        logs = container.logs().decode("utf-8", errors="replace")

        if exit_code == 0:
            return {"status": "success", "output": logs, "error": None}
        return {"status": "failed", "output": logs, "error": f"exit code {exit_code}"}

    except Exception as e:
        err_msg = str(e)
        is_timeout = "timeout" in err_msg.lower() or "timed out" in err_msg.lower()
        if container and is_timeout:
            try:
                container.kill()
            except Exception:
                pass
        return {
            "status": "failed", "output": "",
            "error": f"执行超时（{timeout}s）" if is_timeout else err_msg,
        }
    finally:
        if container:
            try:
                container.remove(force=True)
            except Exception:
                logger.warning("sandbox 容器清理失败", exc_info=True)
