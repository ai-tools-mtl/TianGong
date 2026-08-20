class AppError(Exception):
    """所有自定义异常基类。status_code 决定 HTTP 响应。"""
    status_code: int = 500
    code: str = "internal_error"

    def __init__(self, message: str = "", code: str | None = None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


class UnauthorizedError(AppError):
    status_code = 401
    code = "unauthorized"


class ForbiddenError(AppError):
    status_code = 403
    code = "forbidden"


class AuthorizationError(ForbiddenError):
    """鉴权/权限不足错误(ForbiddenError 的语义化别名)。

    用于"已登录但缺少权限"的场景,如非 admin 触发 global-only 操作。
    保留独立类名便于上层按异常类型分支处理,响应码仍是 403。
    """
    code = "forbidden"


class ValidationError(AppError):
    status_code = 422
    code = "validation_error"


class ServiceUnavailableError(AppError):
    """依赖的外部服务不可用（如 drawio 渲染容器故障）。fail-closed 语义：
    不降级、不留半成品，直接报错让用户重试。"""
    status_code = 503
    code = "service_unavailable"


def register_exception_handlers(app) -> None:
    """注册全局异常处理器，统一错误响应格式 {code, message}。

    所有异常都会落日志（之前 AppError handler 不记日志，未捕获异常走 FastAPI
    默认 500 无 traceback）：
    - AppError：4xx warning、5xx error，记 code/message/request_id。
    - 其他 Exception：exception 级打完整 traceback，返回统一 internal_error，
      生产响应体不泄露堆栈（服务端日志有完整记录）。
    """
    from fastapi import Request
    from fastapi.encoders import jsonable_encoder
    from fastapi.exceptions import RequestValidationError
    from fastapi.responses import JSONResponse

    from app.core.logging import get_request_id, get_logger
    logger = get_logger(__name__)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        # 422 之前走 FastAPI 默认处理器，后台只有一行 access log，
        # 不知道哪个字段/为什么校验失败——排障时最常见的日志盲区。
        # 响应体保持默认 {detail: errors} 格式不变（前端可能依赖该结构）。
        logger.warning(
            "参数校验失败 {method} {path} | {errors}",
            method=request.method, path=request.url.path,
            errors=exc.errors(),
        )
        return JSONResponse(
            status_code=422,
            # errors() 的 ctx 可能含 ValueError 等异常对象，须 jsonable_encoder
            # 规范化（FastAPI 默认处理器同款），否则响应序列化 TypeError。
            content={"detail": jsonable_encoder(exc.errors())},
            headers={"X-Request-ID": get_request_id()},
        )

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError):
        # 4xx 记 warning（客户端错误，非服务故障）；5xx 记 error（服务端问题）
        log = logger.warning if exc.status_code < 500 else logger.error
        log(
            "AppError {code} {status} {method} {path} | {msg}",
            code=exc.code, status=exc.status_code,
            method=request.method, path=request.url.path,
            msg=exc.message,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": exc.code, "message": exc.message},
            headers={"X-Request-ID": get_request_id()},
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        # 兜底：所有非 AppError 异常。logger.exception 打完整 traceback（含 from cause 链）。
        logger.exception(
            "未捕获异常 {method} {path} | {exc}",
            method=request.method, path=request.url.path, exc=exc,
        )
        # 生产不泄露内部堆栈给前端；request_id 写响应体方便用户报错时定位。
        # 注意：异常走此 handler 时中间件已 raise，无法给 response 写 header，
        # 故在此补 X-Request-ID（前端/调用方仍能从响应头拿到）。
        return JSONResponse(
            status_code=500,
            content={
                "code": "internal_error",
                "message": "服务器内部错误，请稍后重试",
                "request_id": get_request_id(),
            },
            headers={"X-Request-ID": get_request_id()},
        )
