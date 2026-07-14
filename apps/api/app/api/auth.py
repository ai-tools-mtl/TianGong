from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.exceptions import UnauthorizedError
from app.core.security import create_access_token, create_refresh_token
from app.deps import get_current_user
from app.models import User
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UserRead
from app.services.auth_service import authenticate_user, register_user, update_last_login

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
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    user = register_user(db, email=payload.email, password=payload.password, name=payload.name)
    return UserRead(id=str(user.id), email=user.email, name=user.name, role=user.role)


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, response: Response, db: Session = Depends(get_db)):
    user = authenticate_user(db, email=payload.email, password=payload.password)
    if user is None:
        raise UnauthorizedError("邮箱或密码错误")
    update_last_login(db, user)
    access = create_access_token({"sub": str(user.id), "role": user.role})
    refresh = create_refresh_token({"sub": str(user.id)})
    _set_auth_cookies(response, access, refresh)
    return TokenResponse(access_token=access, refresh_token=refresh)


@router.post("/logout")
def logout(response: Response):
    domain = _settings.cookie_domain or None
    response.delete_cookie("access_token", domain=domain)
    response.delete_cookie("refresh_token", domain=domain)
    return {"message": "已登出"}


@router.get("/me", response_model=UserRead)
def me(current_user: User = Depends(get_current_user)):
    return UserRead(
        id=str(current_user.id), email=current_user.email,
        name=current_user.name, role=current_user.role,
    )
