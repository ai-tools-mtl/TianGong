import base64
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt
from cryptography.fernet import Fernet

from app.core.config import get_settings


# ── 密码（bcrypt，72 字节限制需截断） ──
def hash_password(raw: str) -> str:
    # bcrypt 限制 72 字节，超出截断（中文/长密码场景）
    byte_password = raw.encode("utf-8")[:72]
    return bcrypt.hashpw(byte_password, bcrypt.gensalt()).decode("utf-8")


def verify_password(raw: str, hashed: str) -> bool:
    byte_password = raw.encode("utf-8")[:72]
    byte_hashed = hashed.encode("utf-8")
    return bcrypt.checkpw(byte_password, byte_hashed)


# ── JWT ──
def _create_token(data: dict[str, Any], expires_delta: timedelta, token_type: str) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {**data, "type": token_type, "iat": now, "exp": now + expires_delta}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(data: dict[str, Any]) -> str:
    settings = get_settings()
    return _create_token(data, timedelta(minutes=settings.access_token_expire_minutes), "access")


def create_refresh_token(data: dict[str, Any]) -> str:
    settings = get_settings()
    return _create_token(data, timedelta(days=settings.refresh_token_expire_days), "refresh")


def decode_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])


# ── 对称加密（用于 LLM key 等敏感字段） ──
def _get_fernet() -> Fernet:
    settings = get_settings()
    # encryption_key 期望是 base64 编码的 32 字节
    key = base64.urlsafe_b64decode(settings.encryption_key)
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt_value(plaintext: str) -> str:
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt_value(ciphertext: str) -> str:
    return _get_fernet().decrypt(ciphertext.encode()).decode()
