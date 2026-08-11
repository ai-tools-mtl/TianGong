from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.exceptions import UnauthorizedError
from app.core.rate_limit import LOGIN_LIMIT, REGISTER_LIMIT, limiter
from app.core.security import create_access_token, create_refresh_token
from app.deps import get_current_user, get_current_user_from_refresh
from app.models import User
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UserRead
from app.services.auth_service import authenticate_user, register_user, update_last_login
from app.services.invite_service import validate_and_consume

router = APIRouter(prefix="/auth", tags=["auth"])
_settings = get_settings()


def _set_auth_cookies(response: Response, access: str, refresh: str) -> None:
    # domain 为空时不传 domain 参数（TestClient 跨域匹配严格，生产配 domain）
    kwargs = dict(httponly=True, secure=_settings.cookie_secure, samesite="lax")
    if _settings.cookie_domain:
        kwargs["domain"] = _settings.cookie_domain
    response.set_cookie(
        "access_token", access,
        max_age=_settings.access_token_expire_minutes * 60,
        **kwargs,
    )
    response.set_cookie(
        "refresh_token", refresh,
        max_age=_settings.refresh_token_expire_days * 86400,
        **kwargs,
    )


@router.post("/register", response_model=UserRead)
@limiter.limit(REGISTER_LIMIT)
def register(request: Request, payload: RegisterRequest, db: Session = Depends(get_db)):
    # 内部产品化:先核销邀请码(API 层),再建用户(register_user 保持邀请码无关)
    # 两者共用同一 session;若建用户失败,核销回滚(同事务)
    validate_and_consume(db, code=payload.invite_code)
    user = register_user(
        db,
        username=payload.username,
        password=payload.password,
        name=payload.name,
        email=payload.email,
    )
    return UserRead(
        id=str(user.id), username=user.username,
        email=user.email, name=user.name, role=user.role,
    )


@router.post("/login", response_model=TokenResponse)
@limiter.limit(LOGIN_LIMIT)
def login(request: Request, payload: LoginRequest, response: Response, db: Session = Depends(get_db)):
    user = authenticate_user(db, username=payload.username, password=payload.password)
    if user is None:
        raise UnauthorizedError("用户名或密码错误")
    update_last_login(db, user)
    access = create_access_token({"sub": str(user.id), "role": user.role})
    refresh = create_refresh_token({"sub": str(user.id)})
    _set_auth_cookies(response, access, refresh)
    return TokenResponse(access_token=access, refresh_token=refresh)


@router.post("/refresh", response_model=TokenResponse)
def refresh(
    response: Response,
    current_user: User = Depends(get_current_user_from_refresh),
):
    """用 refresh_token 换新 access_token（前端 access 过期 401 时静默调用）。

    MVP 不轮换 refresh token（无 token 家族/撤销表），每次刷新顺带续期 refresh
    cookie 的 max_age——活跃用户长期免登，30 天不活跃才会真正过期。
    """
    access = create_access_token({"sub": str(current_user.id), "role": current_user.role})
    new_refresh = create_refresh_token({"sub": str(current_user.id)})
    _set_auth_cookies(response, access, new_refresh)
    return TokenResponse(access_token=access, refresh_token=new_refresh)


@router.post("/logout")
def logout(response: Response):
    domain = _settings.cookie_domain or None
    response.delete_cookie("access_token", domain=domain)
    response.delete_cookie("refresh_token", domain=domain)
    return {"message": "已登出"}


@router.get("/me", response_model=UserRead)
def me(current_user: User = Depends(get_current_user)):
    return UserRead(
        id=str(current_user.id), username=current_user.username,
        email=current_user.email, name=current_user.name, role=current_user.role,
    )
