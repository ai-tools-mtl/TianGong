import uuid

import jwt
from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.exceptions import UnauthorizedError
from app.core.security import decode_token
from app.models import User


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get("access_token")
    if not token:
        raise UnauthorizedError("未登录")
    try:
        payload = decode_token(token)
    except jwt.InvalidTokenError:
        raise UnauthorizedError("无效的登录凭证")
    if payload.get("type") != "access":
        raise UnauthorizedError("token 类型错误")
    user_id = payload.get("sub")
    if not user_id:
        raise UnauthorizedError("token 缺少用户标识")
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise UnauthorizedError("token 用户标识无效")
    user = db.scalar(select(User).where(User.id == uid))
    if user is None or user.status != "active":
        raise UnauthorizedError("用户不存在或已禁用")
    return user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """校验当前用户是 admin，否则 403。"""
    from app.core.exceptions import ForbiddenError

    if current_user.role != "admin":
        raise ForbiddenError("需要管理员权限")
    return current_user
