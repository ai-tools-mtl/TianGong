"""统一日志配置 —— loguru 为单一出口。

核心解决的问题（见日志体系实施计划）：
1. 项目混用 loguru（16 模块）和标准库 logging（10 模块），两套互不相通，
   标准 logging 默认 WARNING 且无 handler → 那些模块的 debug/info/warning 根本不输出。
   解法：InterceptHandler 把标准库 logging 转发给 loguru，一处接管全盘。

2. request_id 贯穿链路：中间件写入 REQUEST_ID_CTX → loguru patcher 注入到 record
   → format 自动带出；LLMCallLog 也从 contextvar 取值落库。

3. 控制台 + 文件双 sink：终端彩色看实时，文件轮转留 30 天翻历史。
"""
import logging
import multiprocessing
import sys
from contextvars import ContextVar
from typing import Any

from loguru import logger

# request_id 上下文：中间件写入，日志/LLMCallLog 读取。
# 默认空串（无请求上下文时，如 startup / 后台任务）。
REQUEST_ID_CTX: ContextVar[str] = ContextVar("request_id", default="-")


def set_request_id(request_id: str) -> None:
    """中间件调用：把当前请求的 request_id 写入 contextvar。"""
    REQUEST_ID_CTX.set(request_id)


def get_request_id() -> str:
    """取当前请求的 request_id（供 LLMCallLog 等落库场景使用）。"""
    return REQUEST_ID_CTX.get()


# 统一日志格式：时间 | 级别 | req_id | 模块:行号 | 消息
_LOG_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{extra[request_id]}</cyan> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
    "<level>{message}</level>"
)


class InterceptHandler(logging.Handler):
    """把标准库 logging 的记录转发给 loguru。

    所有 logging.getLogger(...) 打的日志都会经这里转成 loguru record，
    从而走统一的 sink（控制台/文件）和格式。uvicorn/sqlalchemy/httpx
    等第三方库的日志也一并接管。
    """

    def emit(self, record: logging.LogRecord) -> None:
        # 标准 logging level → loguru level
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # 找到真正发出日志的调用栈深度（跳过 logging 内部帧）
        frame, depth = logging.currentframe(), 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )


def setup_logging(settings: Any) -> None:
    """装配日志系统。必须在 main.py 最顶部、FastAPI 实例化前调用一次。

    Args:
        settings: Settings 实例，读 log_level / log_dir / log_file_enabled。
    """
    level = getattr(settings, "log_level", "INFO")

    # 清掉 loguru 默认 sink，重新装配
    logger.remove()

    # patcher：每条日志注入当前 request_id（从 contextvar 取）
    logger.configure(patcher=lambda record: record["extra"].update(
        request_id=REQUEST_ID_CTX.get()
    ))

    # 控制台 sink（彩色，stderr）
    logger.add(
        sys.stderr,
        format=_LOG_FORMAT,
        level=level,
        colorize=True,
        backtrace=True,
        # diagnose=False（P0-7 安全加固）：diagnose=True 会在异常时打印本地变量值，
        # 生产环境会泄漏密钥/token/用户数据等敏感信息。backtrace=True 保留（只含调用栈，无变量值）。
        diagnose=False,
    )

    # 文件 sink（轮转 + 压缩，留底）。测试环境可关。
    if getattr(settings, "log_file_enabled", True):
        import os

        # Windows + uvicorn --reload 多进程冲突修复：
        # reload 模式下 reloader（父进程）和 worker（子进程，SpawnProcess-N）都 import
        # main.py，都调 setup_logging，都打开同一个 api.log。文件轮转 os.rename 时因
        # 另一进程持有句柄失败（WinError 32），无限重试刷屏。
        #
        # 修复策略：reloader 进程不配置文件 sink。识别依据：
        # - uvicorn reload 父进程是主进程（multiprocessing parent），sys.argv 含 --reload
        # - worker 子进程由 uvicorn 经 multiprocessing spawn，其 process name 是 SpawnProcess-N
        #   且没有 --reload 参数（它只是被 import 后 serve）
        #
        # 检测：当前进程名以 SpawnProcess 开头 → 是 worker → 开文件 sink；
        # 否则（主进程/reloader，或非 uvicorn 场景如脚本/测试）→ 也开（测试环境已用
        # log_file_enabled=False 关闭）。但 uvicorn reload 的主进程会重复开——为彻底
        # 避免冲突，reload 场景下：只有 worker（SpawnProcess）开文件 sink，主进程只 stderr。
        _is_mp_worker = (
            multiprocessing.current_process().name != "MainProcess"
        )
        _is_uvicorn_reload = any("--reload" in str(a) for a in sys.argv)

        if _is_uvicorn_reload and not _is_mp_worker:
            # uvicorn --reload 的父进程（reloader）：只 stderr，不碰文件
            pass
        else:
            log_dir = getattr(settings, "log_dir", "logs")
            os.makedirs(log_dir, exist_ok=True)
            logger.add(
                os.path.join(log_dir, "api.log"),
                format=_LOG_FORMAT,
                level="DEBUG",  # 文件全量留底，便于排查
                rotation="10 MB",
                retention="30 days",
                compression="zip",
                encoding="utf-8",
                backtrace=True,
                diagnose=False,  # P0-7：同上，禁止打印本地变量值防泄漏
                # enqueue=True：写操作交后台线程串行化（多线程安全 + 性能）。
                # 配合上面的 reloader 跳过，彻底消除 Windows 下文件轮转竞争。
                enqueue=True,
            )

    # 桥接标准库 logging → loguru
    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)

    # 接管常用第三方库的 logger（它们直接用 logging.getLogger，不经 root 也得指过来）
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access",
                 "sqlalchemy", "httpx", "httpcore"):
        logging.getLogger(name).handlers = [InterceptHandler()]
        logging.getLogger(name).propagate = False


def get_logger(name: str = __name__):
    """统一 logger 获取门面。

    新代码推荐用本函数。旧代码的 `logging.getLogger(__name__)` 经
    InterceptHandler 桥接也自动生效，无需逐个改 import。
    """
    return logger.bind(name=name)
