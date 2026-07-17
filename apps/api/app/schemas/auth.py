import re

from pydantic import BaseModel, EmailStr, Field, field_validator


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    email: EmailStr | None = None  # 可选联系方式
    password: str = Field(min_length=8, max_length=128)
    name: str = Field(min_length=1, max_length=100)

    @field_validator("username")
    @classmethod
    def _username_format(cls, v: str) -> str:
        """username 仅允许字母数字下划线连字符（避免中文/特殊字符的 URL 编码坑）。"""
        if not re.match(r"^[a-zA-Z0-9_-]+$", v):
            raise ValueError("用户名仅允许字母、数字、下划线和连字符")
        return v


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserRead(BaseModel):
    id: str
    username: str
    email: EmailStr | None = None
    name: str
    role: str
