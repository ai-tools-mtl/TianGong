"""HTTP 中间件：request-id 注入 + 请求日志。

request-id 贯穿链路：
  请求头 X-Request-ID（透传/生成）→ REQUEST_ID_CTX（loguru format 自动带出）
  → 响应头 X-Request-ID（前端/调用方能拿到）→ LLMCallLog.request_id（跨表关联）。

实现「用户报错 → 拿 request_id → 服务端日志/LLM 调用记录一查到底」。
"""
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import set_request_id, get_logger

logger = get_logger(__name__)

_REQUEST_ID_HEADER = "X-Request-ID"


class RequestIDMiddleware(BaseHTTPMiddleware):
    """注入 request_id 并记录每个请求的方法/路径/状态码/耗时。

    放在 CORS 之前注册（main.py 里先 add_middleware 本中间件），
    确保所有后续中间件与路由都在 request_id 上下文内执行。
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # 透传上游的 request_id（链路追踪场景），无则生成 12 位短 id
        request_id = request.headers.get(_REQUEST_ID_HEADER) or uuid.uuid4().hex[:12]
        set_request_id(request_id)

        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            # 异常会冒泡到 exception_handler 兜底打 traceback，这里只记耗时
            duration_ms = (time.perf_counter() - start) * 1000
            logger.error(
                "请求异常 {method} {path} | {duration:.0f}ms",
                method=request.method, path=request.url.path, duration=duration_ms,
            )
            raise

        duration_ms = (time.perf_counter() - start) * 1000
        response.headers[_REQUEST_ID_HEADER] = request_id

        # 慢请求（>1s）记 warning，正常 INFO。让慢请求在日志里显眼。
        status = response.status_code
        log = (
            logger.warning if duration_ms > 1000 or status >= 500
            else logger.info
        )
        log(
            "{method} {path} {status} | {duration:.0f}ms",
            method=request.method, path=request.url.path,
            status=status, duration=duration_ms,
        )
        return response
