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


def register_exception_handlers(app) -> None:
    """注册全局异常处理器，统一错误响应格式 {code, message}。"""
    from fastapi import Request
    from fastapi.responses import JSONResponse

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError):
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": exc.code, "message": exc.message},
        )
