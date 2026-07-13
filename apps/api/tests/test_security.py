import jwt
import pytest
from app.core.security import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    decode_token,
    encrypt_value,
    decrypt_value,
)


def test_password_hash_and_verify():
    raw = "MyPass123!"
    hashed = hash_password(raw)
    assert hashed != raw
    assert verify_password(raw, hashed) is True
    assert verify_password("wrong", hashed) is False


def test_access_token_roundtrip():
    token = create_access_token({"sub": "user-abc", "role": "user"})
    payload = decode_token(token)
    assert payload["sub"] == "user-abc"
    assert payload["role"] == "user"
    assert payload["type"] == "access"


def test_refresh_token_has_correct_type():
    token = create_refresh_token({"sub": "user-abc"})
    payload = decode_token(token)
    assert payload["type"] == "refresh"


def test_decode_invalid_token_raises():
    with pytest.raises(jwt.InvalidTokenError):
        decode_token("not.a.valid.token")


def test_encrypt_decrypt_roundtrip():
    secret = "sk-abcdefghij123456"
    enc = encrypt_value(secret)
    assert enc != secret
    assert decrypt_value(enc) == secret
