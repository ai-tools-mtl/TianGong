# apps/api/tests/test_rate_limit.py
"""P0-5：速率限制（slowapi）集成测试。

验证：
1. limiter 已注册到 app.state
2. RateLimitExceeded 异常 handler 返回 429
3. key_func 正确区分 user_id（已登录）和 IP（未登录）
4. 限流装饰器正确挂在敏感端点上

主测试套件（conftest 的 app_obj fixture）已关闭 limiter，避免 TestClient 快速
请求误触发。此处用独立 app（limiter.enabled=True）验证限流逻辑。
"""
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.core.rate_limit import (
    AI_LIMIT,
    LOGIN_LIMIT,
    _user_or_ip_key,
    limiter,
    register_rate_limit,
)


@pytest.fixture(autouse=True)
def _ensure_limiter_enabled():
    """本文件的限流测试需要 limiter 开启。

    conftest 的 app_obj fixture 会关 limiter（limiter.enabled=False）影响全测试套件。
    此处开启供本文件测试用，**测试后恢复为 False**——避免污染后续测试（全局单例）。
    """
    limiter.enabled = True
    yield
    limiter.enabled = False  # 恢复：后续测试默认不限流（与 conftest 一致）


def _make_test_app(test_limiter=None):
    """构造独立测试 app，用独立的 limiter 实例（避免全局计数器污染）。

    默认创建新 Limiter——每个测试 app 用独立限流器，测试间互不影响。
    """
    from slowapi import Limiter
    from slowapi.util import get_remote_address

    if test_limiter is None:
        test_limiter = Limiter(key_func=get_remote_address)

    def _user_key(request):
        return _user_or_ip_key(request)

    app = FastAPI()
    app.state.limiter = test_limiter
    from slowapi.middleware import SlowAPIMiddleware
    app.add_middleware(SlowAPIMiddleware)
    from slowapi import _rate_limit_exceeded_handler
    from slowapi.errors import RateLimitExceeded
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    @app.post("/login")
    @test_limiter.limit(LOGIN_LIMIT)
    def login(request: Request):
        return {"ok": True}

    @app.post("/ai")
    @test_limiter.limit(AI_LIMIT, key_func=_user_or_ip_key)
    def ai_call(request: Request):
        return {"ok": True}

    return app


def test_limiter_registered_on_app_state():
    """register_rate_limit 把 limiter 挂到 app.state.limiter。"""
    from fastapi import FastAPI
    app = FastAPI()
    register_rate_limit(app)
    assert hasattr(app.state, "limiter")
    assert app.state.limiter is limiter  # register_rate_limit 用全局 limiter 实例


def test_login_rate_limit_returns_429():
    """登录端点超限后返回 429。"""
    app = _make_test_app()
    # LOGIN_LIMIT="5/minute"，第 6 次应被限流
    with TestClient(app) as client:
        for i in range(5):
            r = client.post("/login")
            assert r.status_code == 200, f"第 {i+1} 次应成功"
        r = client.post("/login")
        assert r.status_code == 429, f"第 6 次应被限流，实际 {r.status_code}"


def test_ai_rate_limit_returns_429():
    """AI 端点按 user_id 限流，超限后 429。"""
    app = _make_test_app()
    # AI_LIMIT="20/minute"，快速打 21 次
    with TestClient(app) as client:
        for i in range(20):
            r = client.post("/ai")
            assert r.status_code == 200, f"第 {i+1} 次应成功，实际 {r.status_code}"
        r = client.post("/ai")
        assert r.status_code == 429, f"第 21 次应被限流，实际 {r.status_code}"


def test_user_or_ip_key_extracts_user_id_from_cookie():
    """_user_or_ip_key 从 access_token cookie 解析 user_id。"""
    from app.core.security import create_access_token
    import uuid

    user_id = str(uuid.uuid4())
    token = create_access_token({"sub": user_id, "role": "user", "type": "access"})

    class _FakeRequest:
        cookies = {"access_token": token}

    key = _user_or_ip_key(_FakeRequest())
    assert key == f"user:{user_id}"


def test_user_or_ip_key_falls_back_to_ip_without_cookie():
    """无 cookie 时回退到 IP。"""
    class _FakeRequest:
        cookies = {}
        # get_remote_address 需要的属性
        class client:
            host = "127.0.0.1"

    key = _user_or_ip_key(_FakeRequest())
    # 回退到 IP（get_remote_address 返回 client.host）
    assert "127.0.0.1" in key or key.startswith("user:") is False


def test_rate_limit_decorators_applied():
    """验证敏感端点函数确实被 @limiter.limit 装饰（通过 __wrapped__ 链检查）。

    slowapi 的 limit 装饰器用 functools.wraps 包装，原函数可通过 __wrapped__ 访问。
    装饰后的函数会有 __wrapped__ 属性（指向原始 async def）。
    """
    from app.api.auth import router as auth_router
    from app.api.ai import router as ai_router
    from app.api.assistant import router as asm_router

    # login / register（auth 路由）
    login_fn = next(r for r in auth_router.routes if r.path == "/auth/login").endpoint
    register_fn = next(r for r in auth_router.routes if r.path == "/auth/register").endpoint
    assert hasattr(login_fn, "__wrapped__"), "login 应被 @limiter.limit 装饰"
    assert hasattr(register_fn, "__wrapped__"), "register 应被 @limiter.limit 装饰"

    # chat / generate / rewrite（ai 路由）
    chat_fn = next(r for r in ai_router.routes if r.path.endswith("/chat")).endpoint
    assert hasattr(chat_fn, "__wrapped__"), "ai chat 应被 @limiter.limit 装饰"

    # init chat / generate（assistant 路由，path 含 prefix）
    init_chat_fn = next(
        r for r in asm_router.routes if r.path == "/assistant/conversations/{conv_id}/chat"
    ).endpoint
    assert hasattr(init_chat_fn, "__wrapped__"), "assistant chat 应被 @limiter.limit 装饰"
