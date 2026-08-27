"""doctor 体检脚本测试（批次 E）：退出码分级语义 + env 脱敏保险丝。"""
from scripts.doctor import (
    FAIL_CLOSED,
    FAIL_OPEN,
    HARD,
    INFO,
    CheckResult,
    decide_exit,
    render_text,
)
from app.sandbox.docker_runner import sanitize_env


def _r(name="x", hardness=HARD, ok=True):
    return CheckResult(name=name, hardness=hardness, ok=ok, detail="d")


# ── decide_exit：分级语义的纯函数钉死 ────────────────────────────────────────

def test_all_ok_exits_zero():
    assert decide_exit([_r(), _r(hardness=FAIL_OPEN, ok=False), _r(hardness=INFO)]) == 0


def test_hard_failure_exits_one():
    assert decide_exit([_r(name="postgres", ok=False), _r()]) == 1
    assert decide_exit([_r(name="minio", hardness=HARD, ok=False)]) == 1


def test_drawio_down_is_fail_closed_and_blocks_exit():
    """drawio 挂 = 附图生成整体 503（fail-closed）→ 环境不算就绪。"""
    assert decide_exit([_r(name="drawio 渲染微服务", hardness=FAIL_CLOSED, ok=False)]) == 1


def test_nli_down_keeps_green():
    """NLI 挂 = fail-open 仅降级 neutral，可继续运行 → exit 0。"""
    code = decide_exit([
        _r(name="NLI 记忆矛盾判断", hardness=FAIL_OPEN, ok=False),
        _r(),
    ])
    assert code == 0


def test_info_failure_alone_does_not_block():
    assert decide_exit([_r(name="全局 chat 配置", hardness=INFO, ok=False)]) == 0


# ── render_text：报告形态 ───────────────────────────────────────────────────

def test_render_text_contains_tags_and_hint_on_failure():
    results = [
        _r(name="postgres", ok=True),
        CheckResult("minio", HARD, False, "不可达", hint="起 docker"),
    ]
    text = render_text(results, skipped=False)
    assert "[硬依赖]" in text and "✗" in text
    assert "↳ 起 docker" in text       # 失败项必须带处置建议
    assert "exit=1" in text


# ── sanitize_env：密钥保险丝 ────────────────────────────────────────────────

def test_sanitize_env_strips_sensitive_keys_case_insensitive():
    env = {
        "OPENAI_API_KEY": "sk-x",
        "deepseek_secret": "s",
        "AUTH_TOKEN": "t",
        "DB_PASSWORD": "p",
        "my_passwd": "q",
        "HOME": "/root",
        "PYTHONPATH": "/app",
    }
    out = sanitize_env(env)
    assert set(out) == {"HOME", "PYTHONPATH"}
    # 原 dict 不被改动（返回新 dict）
    assert "OPENAI_API_KEY" in env


def test_sanitize_env_handles_empty_and_non_standard_values():
    assert sanitize_env({}) == {}
    assert sanitize_env(None) == {}
    # 值类型不挑（未来可能传非 str 值），只按键名过滤
    assert sanitize_env({"PATH": 123, "api_key": None}) == {"PATH": 123}
