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


class ValidationError(AppError):
    status_code = 422
    code = "validation_error"
