"""速率限制配置（P0-5）。

用 slowapi 对敏感端点做速率限制：
- 登录/注册：防暴力破解、邀请码枚举（按 IP 限流）
- AI 调用（chat/generate/rewrite/init）：防成本 DoS（按 user_id 限流）

slowapi 的工作方式：
1. limiter 实例挂在 app.state.limiter
2. SlowAPIMiddleware 注册为中间件
3. RateLimitExceeded 异常 handler 转成 429 响应
4. 端点用 @limiter.limit("5/minute") 装饰器声明限流，key_func 决定按什么维度计数

key_func 策略：
- 已登录端点（AI 调用）：按 user_id（精确到用户，防单用户刷量）
- 未登录端点（login/register）：按 IP（防分布式暴力破解）

测试环境通过 conftest 的 app_obj fixture 关闭 limiter（limiter.enabled = False），
避免 TestClient 请求间隔触发限流。
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

# 全局 limiter 实例。key_func 默认按 IP，AI 端点用专用 key_func 覆盖为 user_id。
limiter = Limiter(key_func=get_remote_address)


def _user_or_ip_key(request) -> str:
    """AI 端点限流 key：已登录取 user_id，未登录回退 IP。

    用法：@limiter.limit("20/minute", key_func=_user_or_ip_key)
    user_id 从已认证的 request.state 取（get_current_user 解析后未存 state，
    故从 cookie 解析 access_token 提取 sub）。解析失败回退 IP。
    """
    # 尝试从 cookie 的 access_token 解析 user_id（与 deps.py 同逻辑，但不查 DB 省 IO）
    token = request.cookies.get("access_token")
    if token:
        try:
            import jwt
            from app.core.config import get_settings
            payload = jwt.decode(
                token, get_settings().jwt_secret,
                algorithms=[get_settings().jwt_algorithm], options={"verify_exp": False},
            )
            sub = payload.get("sub")
            if sub and payload.get("type") == "access":
                return f"user:{sub}"
        except Exception:
            pass  # 解析失败回退 IP
    return get_remote_address(request)


def register_rate_limit(app) -> None:
    """注册 limiter + 中间件 + 异常 handler。在 main.py 装配路由前调用。"""
    from slowapi import _rate_limit_exceeded_handler
    from slowapi.errors import RateLimitExceeded
    from slowapi.middleware import SlowAPIMiddleware

    app.state.limiter = limiter
    app.add_middleware(SlowAPIMiddleware)
    # RateLimitExceeded → 429 响应（与项目 {code, message} 格式对齐）
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# 限流策略常量（供路由装饰器引用，集中管理）
LOGIN_LIMIT = "5/minute"        # 登录：5 次/分钟/IP（防暴力破解）
REGISTER_LIMIT = "3/minute"     # 注册：3 次/分钟/IP（防邀请码枚举）
AI_LIMIT = "20/minute"          # AI 调用：20 次/分钟/user（防成本 DoS，正常使用不受影响）
