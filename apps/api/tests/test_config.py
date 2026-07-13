from app.core.config import Settings


def test_settings_loads_from_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://t:t@localhost/t")
    monkeypatch.setenv("JWT_SECRET", "x" * 64)
    monkeypatch.setenv("ENCRYPTION_KEY", "YWJjZGVmZ2hpamtsbW5vcHFyc3R1dnd4eXoxMjM0NTY=")
    s = Settings()
    assert s.database_url.startswith("postgresql://")
    assert len(s.jwt_secret) >= 32
    assert s.access_token_expire_minutes == 30


def test_cors_origins_parses_csv(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://t:t@localhost/t")
    monkeypatch.setenv("JWT_SECRET", "x" * 64)
    monkeypatch.setenv("ENCRYPTION_KEY", "YWJjZGVmZ2hpamtsbW5vcHFyc3R1dnd4eXoxMjM0NTY=")
    monkeypatch.setenv("CORS_ORIGINS", "http://a.com,http://b.com")
    s = Settings()
    assert s.cors_origins == ["http://a.com", "http://b.com"]
