# apps/api/tests/test_logging_security_config.py
"""P0-7 + P0-6：日志 diagnose 关闭 + 弱密钥告警。

P0-7：loguru 的 stderr/file sink 的 diagnose 必须 False（防异常时打印本地变量
      泄漏密钥/token/用户数据）。
P0-6：非测试环境下，Settings 检测到弱密钥打 ERROR 告警（不阻断启动）。
"""
import os

import pytest


@pytest.fixture(autouse=True)
def _isolate_settings_cache(monkeypatch):
    """把本文件的 get_settings 替换成替身，真 lru_cache 原封不动。

    本文件需要绕过缓存、按当次 env 现建 Settings 验证 validator，原实现靠
    cache_clear 清真缓存。但被清掉的缓存实例（A）已被 app.main 等模块在
    导入期捕获；离场后缓存里是新实例（B），conftest 的 _clear_cookie_domain
    会补丁到 B，而 auth 读 A（cookie_domain='localhost'）→ httpx 拒收
    Domain=localhost 的 cookie → 全套后续 client 测试 401
    （同 test_rag_config.py 头注释记录的坑；3.14 起 lru_cache 无 .cache
    内部字典可快照，故整函数换身）。
    """
    from app.core import config as config_mod

    class _SettingsStub:
        @staticmethod
        def cache_clear():
            pass  # 替身无缓存，clear 是空操作

        def __call__(self):
            return config_mod.Settings.from_env()

    monkeypatch.setattr(config_mod, "get_settings", _SettingsStub())


# ── P0-7：diagnose=False ───────────────────────────────────────────────

def test_loguru_sinks_have_diagnose_disabled(monkeypatch):
    """所有 loguru sink 的 diagnose 必须为 False（P0-7 安全加固）。

    用 spy 拦截 logger.add 的调用，断言传参 diagnose=False。
    """
    from loguru import logger

    added_kwargs = []
    original_add = logger.add

    def _spy_add(*args, **kwargs):
        added_kwargs.append(kwargs)
        return original_add(*args, **kwargs)

    monkeypatch.setattr(logger, "add", _spy_add)

    from app.core.logging import setup_logging
    from app.core.config import get_settings
    setup_logging(get_settings())

    assert len(added_kwargs) >= 1
    for kw in added_kwargs:
        assert kw.get("diagnose") is False, (
            f"logger.add 的 diagnose 必须为 False，实际: {kw.get('diagnose')}（kwargs: {kw}）"
        )


# ── P0-6：弱密钥告警 ───────────────────────────────────────────────────

def _reset_and_make_settings(monkeypatch, **env_overrides):
    """用指定 env 构造 Settings（绕过 lru_cache + conftest 的 TIANGONG_TESTING=1）。"""
    monkeypatch.delenv("TIANGONG_TESTING", raising=False)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///test.db")
    monkeypatch.setenv("TEST_DATABASE_URL", "sqlite:///test.db")
    for k, v in env_overrides.items():
        monkeypatch.setenv(k, v)
    from app.core import config as config_mod
    config_mod.get_settings.cache_clear()
    return config_mod


def test_weak_secret_warning_triggers(monkeypatch):
    """非测试环境 + 弱密钥 → loguru.logger.error 被调用。"""
    config_mod = _reset_and_make_settings(
        monkeypatch,
        JWT_SECRET="change-me-to-a-random-64-char-string",
        ENCRYPTION_KEY="YWJjZGVmZ2hpamtsbW5vcHFyc3R1dnd4eXoxMjM0NTY=",
        MINIO_SECRET_KEY="tiangong12345",
    )

    errors = []
    import loguru
    monkeypatch.setattr(loguru.logger, "error", lambda msg, *a, **k: errors.append(str(msg)))

    config_mod.get_settings()  # 触发 validator

    assert any("JWT_SECRET" in e for e in errors), f"应告警 JWT_SECRET，实际 errors: {errors}"
    assert any("MINIO_SECRET_KEY" in e for e in errors), "应告警 MINIO_SECRET_KEY"
    assert any("ENCRYPTION_KEY" in e for e in errors), "应告警 ENCRYPTION_KEY"

    config_mod.get_settings.cache_clear()


def test_weak_secret_warning_skipped_in_testing(monkeypatch):
    """测试环境（TIANGONG_TESTING=1）跳过告警。"""
    monkeypatch.setenv("TIANGONG_TESTING", "1")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///test.db")
    monkeypatch.setenv("JWT_SECRET", "change-me-to-a-random-64-char-string")
    monkeypatch.setenv("ENCRYPTION_KEY", "valid-random-key-not-in-blacklist-32chars!!")

    from app.core import config as config_mod
    config_mod.get_settings.cache_clear()

    errors = []
    import loguru
    monkeypatch.setattr(loguru.logger, "error", lambda msg, *a, **k: errors.append(str(msg)))

    config_mod.get_settings()

    assert not any("安全告警" in e for e in errors), "测试环境不应触发弱密钥告警"

    config_mod.get_settings.cache_clear()


def test_strong_secret_no_warning(monkeypatch):
    """强密钥不触发告警。"""
    _reset_and_make_settings(
        monkeypatch,
        JWT_SECRET="a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0u1v2w3x4y5z6",
        ENCRYPTION_KEY="Z9Y8X7W6V5U4T3S2R1Q0P9O8N7M6L5K4J3I2H1G0==",
        MINIO_SECRET_KEY="a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6",
        FIRECRAWL_API_KEY="fc-real-random-key-12345",
    )

    errors = []
    import loguru
    monkeypatch.setattr(loguru.logger, "error", lambda msg, *a, **k: errors.append(str(msg)))

    from app.core import config as config_mod
    config_mod.get_settings()

    secret_warnings = [e for e in errors if "安全告警" in e]
    assert not secret_warnings, f"强密钥不应触发告警，实际: {secret_warnings}"

    config_mod.get_settings.cache_clear()
