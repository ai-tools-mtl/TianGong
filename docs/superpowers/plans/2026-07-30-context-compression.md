# 对话上下文压缩 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为天工 AI agent 新增运行时对话历史压缩，双闸触发（条数>30 或 token>24000），触发后保留首条+最近10条+中段摘要，两条路径（章节 chat/generate + init 助手）共用，原始 Message 表不污染。

**Architecture:** 新增独立模块 `app/ai/context_compactor.py`，在「装配 messages 喂给 LLM 前」做压缩（取数层不动）。压缩输出 `list[dict]` + `Snapshot`（观测记录，持久化到 `LLMCallLog.context_meta`）。摘要用用户自己的 chat 配置生成，配置类错误抛出、运行时失败降级硬截断。路径A 关掉 deepagents 默认 SummarizationMiddleware 换成自己的。

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0, Alembic, LangChain (ChatOpenAI), pytest, SQLite 内存库（测试，遵循 GOTCHAS G2）

**参考文档:** [设计文档](../specs/2026-07-30-context-compression-design.md)

---

## 文件结构

**新建：**
- `apps/api/app/ai/context_compactor.py` — 压缩核心模块。职责单一：输入 `(history, current_input, llm_config, budget)` → 输出 `(compressed_messages, snapshot)`。含 `BudgetConfig` / `Snapshot` / `estimate_tokens` / `should_compress` / `summarize` / `compress_history`。
- `apps/api/tests/test_context_compactor.py` — 单元测试（纯逻辑，mock LLM）。
- `apps/api/tests/test_orchestrator_compression.py` — 集成测试（orchestrator/init 端到端）。
- `apps/api/alembic/versions/<new>_add_llm_call_log_context_meta.py` — 给 `llm_call_logs` 加 `context_meta` JSON 列。

**修改：**
- `apps/api/app/models/llm_call_log.py` — 加 `context_meta` 字段。
- `apps/api/app/api/ai.py:103-131` — `_log_llm_call` 透传 snapshot 到 `context_meta`。
- `apps/api/app/ai/orchestrator.py:112-169`（astream_chat）、`171-231`（astream_generate）— 装配前调 `compress_history`。
- `apps/api/app/ai/init_orchestrator.py:52-61`（_build_init_chat_messages）、`77-94`（_build_section_generate_messages）— 装配前调 `compress_history`。
- `apps/api/app/ai/agent.py:114-121` — `create_deep_agent` 加 `excluded_middleware` 关掉库默认 SummarizationMiddleware。

---

## Task 1: BudgetConfig 与 Snapshot 数据结构

**Files:**
- Create: `apps/api/app/ai/context_compactor.py`
- Test: `apps/api/tests/test_context_compactor.py`

- [ ] **Step 1: 写失败测试 — BudgetConfig 默认值与 frozen**

```python
# apps/api/tests/test_context_compactor.py
"""上下文压缩模块测试（纯逻辑，mock LLM，SQLite 内存库，遵循 GOTCHAS G2）。"""
from app.ai.context_compactor import BudgetConfig, Snapshot


def test_budget_config_defaults():
    b = BudgetConfig()
    assert b.max_messages == 30
    assert b.token_budget == 24000
    assert b.keep_head == 1
    assert b.keep_tail == 10


def test_budget_config_is_frozen():
    import dataclasses
    b = BudgetConfig()
    assert dataclasses.is_dataclass(b)
    try:
        b.max_messages = 99  # frozen=True 应拒绝
        assert False, "应抛 FrozenInstanceError"
    except dataclasses.FrozenInstanceError:
        pass


def test_snapshot_fields():
    s = Snapshot(
        triggered=True, reason="messages>30",
        original_count=35, compressed_count=12,
        middle_count=24, est_tokens_before=1000, est_tokens_after=400,
    )
    assert s.triggered is True
    assert s.fallback is False  # 默认值
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd apps/api && uv run pytest tests/test_context_compactor.py -v`
Expected: FAIL — `ImportError: cannot import name 'BudgetConfig'`

- [ ] **Step 3: 实现最小代码**

```python
# apps/api/app/ai/context_compactor.py
"""对话上下文压缩：双闸触发 + 首尾保留 + 中段摘要（运行时压缩，不污染原始 Message 表）。

设计见 docs/superpowers/specs/2026-07-30-context-compression-design.md。

职责：输入 (history, current_input, llm_config, budget) → 输出 (compressed_messages, snapshot)。
在「装配 messages 喂给 LLM 前」调用，取数层（_get_section_with_history）不动。
"""
from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class BudgetConfig:
    """压缩预算配置（可调常量，集中管理）。"""
    # 双闸阈值（任一命中即触发）
    max_messages: int = 30          # 条数快闸
    token_budget: int = 24000       # token 慢闸（GLM 128k 窗口的 ~18%）
    # 保留策略
    keep_head: int = 1              # 保留首条 user（原始需求）
    keep_tail: int = 10             # 保留最近 10 条（连续性）


DEFAULT_BUDGET = BudgetConfig()


@dataclass
class Snapshot:
    """单次压缩的观测记录（不落库于 Message 表；序列化进 LLMCallLog.context_meta）。"""
    triggered: bool
    reason: str            # "uncompressed" / "messages>30" / "tokens>24000" / "summarize_failed"
    original_count: int
    compressed_count: int
    middle_count: int
    est_tokens_before: int
    est_tokens_after: int
    fallback: bool = False
```

- [ ] **Step 4: 运行测试验证通过**

Run: `cd apps/api && uv run pytest tests/test_context_compactor.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: 提交**

```bash
git add apps/api/app/ai/context_compactor.py apps/api/tests/test_context_compactor.py
git commit -m "feat(ai): 上下文压缩模块骨架 —— BudgetConfig + Snapshot 数据结构"
```

---

## Task 2: token 估算（estimate_tokens）

**Files:**
- Modify: `apps/api/app/ai/context_compactor.py`
- Test: `apps/api/tests/test_context_compactor.py`

- [ ] **Step 1: 写失败测试**

```python
# 追加到 test_context_compactor.py
from app.ai.context_compactor import estimate_tokens


def test_estimate_tokens_empty():
    assert estimate_tokens("") == 0


def test_estimate_tokens_chinese_weighted_higher_than_english():
    """中文按 ~1.5 字/token（权重高），英文/标点按 ~4 字符/token（权重低）。
    同字符数的中文估算 token 应高于英文。"""
    chinese = "技术方案需要解决的核心问题"  # 12 个 CJK 字符
    english = "abcdefghijkl"  # 12 个 ASCII 字符
    assert estimate_tokens(chinese) > estimate_tokens(english)


def test_estimate_tokens_grows_with_length():
    assert estimate_tokens("短") < estimate_tokens("短" * 100)


def test_estimate_tokens_mixed():
    # 混合文本不报错，返回正整数
    t = estimate_tokens("技术方案 technical solution 123")
    assert t > 0
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd apps/api && uv run pytest tests/test_context_compactor.py::test_estimate_tokens_chinese_weighted_higher_than_english -v`
Expected: FAIL — `ImportError: cannot import name 'estimate_tokens'`

- [ ] **Step 3: 实现 estimate_tokens**

追加到 `context_compactor.py`（`Snapshot` 之后）：

```python
def estimate_tokens(text: str) -> int:
    """轻量 token 近似估算（无 tiktoken）。

    GLM 用不了 tiktoken 的 cl100k 编码（本身也是近似），故用混合字符加权：
    - CJK 字符按 ~1.5 字/token（即每字符 ~0.67 token）
    - 其他字符（英文/标点/数字）按 ~4 字符/token（即每字符 ~0.25 token）

    精度 ±25%，配合条数闸兜底（should_compress），不会明显误判触发。
    """
    if not text:
        return 0
    cjk = sum(1 for ch in text if _is_cjk(ch))
    other = len(text) - cjk
    # 向上取整，避免短文本估为 0
    return max(1, round(cjk / 1.5 + other / 4))


def _is_cjk(ch: str) -> bool:
    """判断字符是否为 CJK 统一表意文字（中日韩）。"""
    code = ord(ch)
    return (
        0x4E00 <= code <= 0x9FFF    # CJK 统一表意文字
        or 0x3400 <= code <= 0x4DBF  # CJK 扩展 A
        or 0x3000 <= code <= 0x303F  # CJK 标点
    )


def estimate_tokens_messages(messages) -> int:
    """对消息列表（Message 对象或 dict）累加 content 的 token 估算。"""
    total = 0
    for m in messages:
        content = m.get("content") if isinstance(m, dict) else getattr(m, "content", "")
        total += estimate_tokens(content or "")
    return total
```

- [ ] **Step 4: 运行测试验证通过**

Run: `cd apps/api && uv run pytest tests/test_context_compactor.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: 提交**

```bash
git add apps/api/app/ai/context_compactor.py apps/api/tests/test_context_compactor.py
git commit -m "feat(ai): 上下文压缩 token 估算 —— 混合字符加权近似"
```

---

## Task 3: 触发判定（should_compress）

**Files:**
- Modify: `apps/api/app/ai/context_compactor.py`
- Test: `apps/api/tests/test_context_compactor.py`

- [ ] **Step 1: 写失败测试**

```python
# 追加到 test_context_compactor.py
from app.ai.context_compactor import should_compress, BudgetConfig


def test_should_compress_false_when_history_too_short():
    # 11 条，keep_head+keep_tail=11，无中段可压
    assert should_compress(11, 100) is False


def test_should_compress_false_under_both_thresholds():
    # 12 条（>11，有中段），token 不超，条数不超 → 不触发
    assert should_compress(12, 1000) is False


def test_should_compress_true_by_message_count():
    # 31 条 > max_messages=30 → 条数闸触发
    assert should_compress(31, 1000) is True


def test_should_compress_true_by_tokens():
    # 12 条，token > budget=24000 → token 闸触发
    assert should_compress(12, 30000) is True


def test_should_compress_respects_custom_budget():
    custom = BudgetConfig(max_messages=5, token_budget=100, keep_head=1, keep_tail=1)
    assert should_compress(6, 50, custom) is True   # 条数闸
    assert should_compress(3, 200, custom) is True  # token 闸
    assert should_compress(2, 50, custom) is False  # 太短
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd apps/api && uv run pytest tests/test_context_compactor.py -k should_compress -v`
Expected: FAIL — `ImportError: cannot import name 'should_compress'`

- [ ] **Step 3: 实现 should_compress**

追加到 `context_compactor.py`：

```python
def should_compress(
    history_count: int, est_tokens: int, budget: BudgetConfig = DEFAULT_BUDGET
) -> bool:
    """双闸触发判定（OR）：条数 > max_messages 或 token > token_budget 即触发。

    先挡「连首尾都凑不齐」的情况（无中段可压）。
    """
    if history_count <= budget.keep_head + budget.keep_tail:
        return False
    if history_count > budget.max_messages:
        return True
    if est_tokens > budget.token_budget:
        return True
    return False
```

- [ ] **Step 4: 运行测试验证通过**

Run: `cd apps/api && uv run pytest tests/test_context_compactor.py -v`
Expected: PASS (12 passed)

- [ ] **Step 5: 提交**

```bash
git add apps/api/app/ai/context_compactor.py apps/api/tests/test_context_compactor.py
git commit -m "feat(ai): 上下文压缩双闸触发判定 —— should_compress"
```

---

## Task 4: 摘要生成 + 分类降级（summarize）

**Files:**
- Modify: `apps/api/app/ai/context_compactor.py`
- Test: `apps/api/tests/test_context_compactor.py`

- [ ] **Step 1: 写失败测试**

```python
# 追加到 test_context_compactor.py
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.ai.context_compactor import summarize, SummarizeRuntimeError, BudgetConfig


def _make_messages(contents: list[str], role: str = "user") -> list:
    """构造简单 Message 替身对象（duck-typed，有 role/content）。"""
    objs = []
    for c in contents:
        m = MagicMock()
        m.role = role
        m.content = c
        objs.append(m)
    return objs


@pytest.mark.asyncio
async def test_summarize_success():
    """mock get_llm 返回摘要文本 → summarize 返回该文本。"""
    msgs = _make_messages(["讨论了技术方案A", "确定了核心模块"])
    fake_llm = MagicMock()
    fake_llm.ainvoke = AsyncMock(return_value=MagicMock(content="摘要：技术方案A含核心模块"))

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.ai.context_compactor.get_llm", lambda *a, **k: fake_llm)
        result = await summarize(msgs, _fake_chat_config())
    assert "技术方案A" in result


@pytest.mark.asyncio
async def test_summarize_empty_response_raises_runtime():
    """摘要返回空 → SummarizeRuntimeError（视为运行时失败，由上层降级）。"""
    msgs = _make_messages(["内容"])
    fake_llm = MagicMock()
    fake_llm.ainvoke = AsyncMock(return_value=MagicMock(content="   "))

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.ai.context_compactor.get_llm", lambda *a, **k: fake_llm)
        with pytest.raises(SummarizeRuntimeError):
            await summarize(msgs, _fake_chat_config())


@pytest.mark.asyncio
async def test_summarize_llm_exception_raises_runtime():
    """LLM 抛超时 → 转 SummarizeRuntimeError（不抛原始异常，统一降级协议）。"""
    msgs = _make_messages(["内容"])
    fake_llm = MagicMock()
    fake_llm.ainvoke = AsyncMock(side_effect=TimeoutError("upstream timeout"))

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.ai.context_compactor.get_llm", lambda *a, **k: fake_llm)
        with pytest.raises(SummarizeRuntimeError):
            await summarize(msgs, _fake_chat_config())


@pytest.mark.asyncio
async def test_summarize_config_error_raises_value_error():
    """llm_config.model 为空 → ValueError（配置类，不降级，向上抛）。"""
    msgs = _make_messages(["内容"])
    bad_config = MagicMock()
    bad_config.model = ""
    with pytest.raises(ValueError):
        await summarize(msgs, bad_config)


@pytest.mark.asyncio
async def test_summarize_none_config_raises_value_error():
    """llm_config=None → ValueError。"""
    msgs = _make_messages(["内容"])
    with pytest.raises(ValueError):
        await summarize(msgs, None)


def _fake_chat_config():
    """构造一个最小可用的 ResolvedChatConfig 替身。"""
    cfg = MagicMock()
    cfg.model = "glm-4"
    cfg.base_url = "http://localhost"
    cfg.api_key = "sk-test"
    return cfg
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd apps/api && uv run pytest tests/test_context_compactor.py -k summarize -v`
Expected: FAIL — `ImportError: cannot import name 'summarize'`

- [ ] **Step 3: 实现 summarize 与 SummarizeRuntimeError**

追加到 `context_compactor.py`（在 `should_compress` 之后）：

```python
from langchain_core.messages import HumanMessage, SystemMessage

from app.ai.llm_client import get_llm
from app.services.llm_config_service import ResolvedChatConfig


class SummarizeRuntimeError(Exception):
    """摘要运行时失败（超时/限流/网络/返回空）。由 compress_history 捕获后降级。"""


SUMMARIZE_PROMPT = """你是对话历史压缩器。把多轮对话压缩成一段高密度摘要，供 AI 撰写助手延续上下文。

必须保留（缺一不可）：
1. 用户确定的技术问题、技术方案、关键术语（原词不换同义词）
2. 已达成的结论、用户明确表达的偏好或约束
3. 待解决/未确定的开放问题

可以省略：寒暄、重复内容、已被后续对话推翻的旧说法。

输出要求：纯文本摘要（不要 Markdown 标题），300 字以内。只输出摘要，不要解释。"""


def _format_for_summary(messages: list) -> str:
    """把消息列表格式化为摘要输入文本。"""
    lines = []
    for m in messages:
        role = m.get("role") if isinstance(m, dict) else getattr(m, "role", "user")
        content = m.get("content") if isinstance(m, dict) else getattr(m, "content", "")
        label = "用户" if role == "user" else "助手"
        lines.append(f"{label}：{content}")
    return "\n".join(lines)


async def summarize(messages: list, llm_config: ResolvedChatConfig | None) -> str:
    """用用户自己的 chat 配置摘要中段消息。

    分类降级协议（spec §5.2）：
    - 配置类错误（无 config / model 空）→ 抛 ValueError（该报则报）。
    - 运行时错误（超时/限流/网络/返回空）→ 抛 SummarizeRuntimeError（由 compress_history 降级）。
    """
    if llm_config is None or not getattr(llm_config, "model", None):
        raise ValueError("LLM 配置缺少 model，无法生成摘要")
    try:
        llm = get_llm(llm_config, streaming=False)
        resp = await llm.ainvoke([
            SystemMessage(content=SUMMARIZE_PROMPT),
            HumanMessage(content=_format_for_summary(messages)),
        ])
        text = (resp.content or "").strip()
        if not text:
            raise SummarizeRuntimeError("摘要返回空")
        return text
    except SummarizeRuntimeError:
        raise
    except ValueError:
        raise
    except Exception as e:
        raise SummarizeRuntimeError(str(e)) from e
```

- [ ] **Step 4: 运行测试验证通过**

Run: `cd apps/api && uv run pytest tests/test_context_compactor.py -v`
Expected: PASS (17 passed)

- [ ] **Step 5: 提交**

```bash
git add apps/api/app/ai/context_compactor.py apps/api/tests/test_context_compactor.py
git commit -m "feat(ai): 上下文压缩摘要生成 —— 分类降级（配置报错/运行时降级）"
```

---

## Task 5: 压缩主流程（compress_history）

**Files:**
- Modify: `apps/api/app/ai/context_compactor.py`
- Test: `apps/api/tests/test_context_compactor.py`

- [ ] **Step 1: 写失败测试**

```python
# 追加到 test_context_compactor.py
from app.ai.context_compactor import compress_history, BudgetConfig
from unittest.mock import AsyncMock, MagicMock


def _make_history(n: int, prefix: str = "msg") -> list:
    """构造 n 条 Message 替身，role 交替 user/assistant，content 含序号。"""
    objs = []
    for i in range(n):
        m = MagicMock()
        m.role = "user" if i % 2 == 0 else "assistant"
        m.content = f"{prefix}-{i}"
        objs.append(m)
    return objs


@pytest.mark.asyncio
async def test_compress_history_not_triggered():
    """12 条、token 低 → 不触发，原样转 dict，snapshot.triggered=False。"""
    history = _make_history(12)
    msgs, snap = await compress_history(history, "current", _fake_chat_config())
    assert snap.triggered is False
    assert snap.reason == "uncompressed"
    assert len(msgs) == 12
    # 原样：content 不变
    assert msgs[0]["content"] == "msg-0"


@pytest.mark.asyncio
async def test_compress_history_triggered_keeps_head_tail():
    """35 条（>30）触发 → 首1 + 摘要 + 尾10。"""
    history = _make_history(35)
    fake_llm = MagicMock()
    fake_llm.ainvoke = AsyncMock(return_value=MagicMock(content="这是摘要"))

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.ai.context_compactor.get_llm", lambda *a, **k: fake_llm)
        msgs, snap = await compress_history(history, "current", _fake_chat_config())

    # 结构：首条(head) + 摘要 + 10条(tail) + current = 13
    assert len(msgs) == 1 + 1 + 10 + 1
    # 首条保留原文
    assert msgs[0]["content"] == "msg-0"
    # 摘要消息 role=user，含前缀
    assert msgs[1]["role"] == "user"
    assert "早期对话历史摘要" in msgs[1]["content"]
    assert "这是摘要" in msgs[1]["content"]
    # 尾部第一条应是 history[-10]
    assert msgs[2]["content"] == "msg-25"  # history[25..34] 是尾部10条
    # 最后一条是 current_input
    assert msgs[-1]["content"] == "current"
    # snapshot
    assert snap.triggered is True
    assert snap.reason == "messages>30"
    assert snap.original_count == 35
    assert snap.middle_count == 24  # 35 - 1(head) - 10(tail)
    assert snap.fallback is False


@pytest.mark.asyncio
async def test_compress_history_runtime_failure_falls_back():
    """摘要运行时失败 → 降级硬截断保首尾，fallback=True。"""
    history = _make_history(35)
    fake_llm = MagicMock()
    fake_llm.ainvoke = AsyncMock(side_effect=TimeoutError("timeout"))

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.ai.context_compactor.get_llm", lambda *a, **k: fake_llm)
        msgs, snap = await compress_history(history, "current", _fake_chat_config())

    assert snap.triggered is True
    assert snap.fallback is True
    assert snap.reason == "summarize_failed"
    # 降级结构：首1 + 尾10 + current = 12（无摘要）
    assert len(msgs) == 1 + 10 + 1
    assert msgs[0]["content"] == "msg-0"
    assert msgs[-1]["content"] == "current"


@pytest.mark.asyncio
async def test_compress_history_config_error_propagates():
    """配置类错误（model 空）→ ValueError 向上抛，不降级。"""
    history = _make_history(35)
    bad_config = MagicMock()
    bad_config.model = ""
    with pytest.raises(ValueError):
        await compress_history(history, "current", bad_config)


@pytest.mark.asyncio
async def test_compress_history_empty_history():
    """空 history → 不抛，原样返回空 + snapshot。"""
    msgs, snap = await compress_history([], "current", _fake_chat_config())
    assert snap.triggered is False
    assert len(msgs) == 0


@pytest.mark.asyncio
async def test_compress_history_token_gate():
    """5 条但 token 超预算 → token 闸触发。"""
    history = _make_history(12)
    # 用极小的 token_budget 强制触发 token 闸
    tiny_budget = BudgetConfig(max_messages=999, token_budget=10, keep_head=1, keep_tail=2)
    fake_llm = MagicMock()
    fake_llm.ainvoke = AsyncMock(return_value=MagicMock(content="摘要"))

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.ai.context_compactor.get_llm", lambda *a, **k: fake_llm)
        msgs, snap = await compress_history(history, "current", _fake_chat_config(), budget=tiny_budget)

    assert snap.triggered is True
    assert snap.reason == "tokens>24000"
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd apps/api && uv run pytest tests/test_context_compactor.py -k compress_history -v`
Expected: FAIL — `ImportError: cannot import name 'compress_history'`

- [ ] **Step 3: 实现 compress_history**

追加到 `context_compactor.py`：

```python
def _msg_to_dict(m) -> dict:
    """Message 对象或 dict → dict{role, content}。"""
    if isinstance(m, dict):
        return {"role": m.get("role", "user"), "content": m.get("content", "")}
    return {"role": getattr(m, "role", "user"), "content": getattr(m, "content", "")}


async def compress_history(
    history: list,
    current_input: str,
    llm_config: ResolvedChatConfig | None,
    *,
    scene: str = "chat",
    budget: BudgetConfig = DEFAULT_BUDGET,
) -> tuple[list[dict], "Snapshot"]:
    """压缩对话历史（核心入口）。

    Args:
        history: 原始消息列表（Message 对象，永不被修改）。
        current_input: 当前用户输入（始终保留在末尾）。
        llm_config: 用户的 chat 配置（用于摘要）。
        scene: 调用场景（"chat"/"generate"/"init"），仅用于日志，不影响逻辑。
        budget: 预算配置。

    Returns:
        (compressed_messages, snapshot)。compressed_messages 是 list[dict]，
        含 {role, content}。未触发时原样转 dict 返回。

    降级协议：摘要运行时失败 → 硬截断保首尾（fallback=True）；配置类错误 → 抛 ValueError。
    """
    if not history:
        return [], Snapshot(triggered=False, reason="uncompressed",
                            original_count=0, compressed_count=0,
                            middle_count=0, est_tokens_before=0, est_tokens_after=0)

    est_tokens = estimate_tokens_messages(history) + estimate_tokens(current_input)
    if not should_compress(len(history), est_tokens, budget):
        msgs = [_msg_to_dict(m) for m in history]
        return msgs, Snapshot(triggered=False, reason="uncompressed",
                              original_count=len(history), compressed_count=len(msgs),
                              middle_count=0, est_tokens_before=est_tokens,
                              est_tokens_after=est_tokens)

    # 触发原因：条数优先（与 should_compress 的判定顺序一致）
    reason = "messages>30" if len(history) > budget.max_messages else "tokens>24000"

    head = history[:budget.keep_head]
    middle = history[budget.keep_head:-budget.keep_tail]
    tail = history[-budget.keep_tail:]

    try:
        summary = await summarize(middle, llm_config)
    except SummarizeRuntimeError:
        # 降级①：硬截断保首尾，中段丢弃（spec §5.2）
        import logging
        logging.getLogger(__name__).warning(
            "上下文压缩摘要失败，降级硬截断 (scene=%s, middle=%d)", scene, len(middle)
        )
        msgs = [_msg_to_dict(m) for m in head] + [_msg_to_dict(m) for m in tail]
        msgs.append({"role": "user", "content": current_input})
        return msgs, Snapshot(
            triggered=True, reason="summarize_failed",
            original_count=len(history), compressed_count=len(msgs),
            middle_count=len(middle), est_tokens_before=est_tokens,
            est_tokens_after=estimate_tokens_messages(msgs), fallback=True,
        )
    # ValueError（配置类）不捕获，向上抛

    compressed: list[dict] = []
    for m in head:
        compressed.append(_msg_to_dict(m))
    compressed.append({
        "role": "user",
        "content": f"[早期对话历史摘要，共{len(middle)}条已归档]\n{summary}",
    })
    for m in tail:
        compressed.append(_msg_to_dict(m))
    compressed.append({"role": "user", "content": current_input})

    return compressed, Snapshot(
        triggered=True, reason=reason,
        original_count=len(history), compressed_count=len(compressed),
        middle_count=len(middle), est_tokens_before=est_tokens,
        est_tokens_after=estimate_tokens_messages(compressed), fallback=False,
    )
```

- [ ] **Step 4: 运行测试验证通过**

Run: `cd apps/api && uv run pytest tests/test_context_compactor.py -v`
Expected: PASS (23 passed)

- [ ] **Step 5: 提交**

```bash
git add apps/api/app/ai/context_compactor.py apps/api/tests/test_context_compactor.py
git commit -m "feat(ai): 上下文压缩主流程 —— compress_history 双闸+首尾保留+中段摘要"
```

---

## Task 6: LLMCallLog 加 context_meta 字段 + 迁移

**Files:**
- Modify: `apps/api/app/models/llm_call_log.py`
- Create: `apps/api/alembic/versions/<new>_add_llm_call_log_context_meta.py`
- Modify: `apps/api/app/api/ai.py:103-131`（_log_llm_call）

- [ ] **Step 1: 修改模型加 context_meta 字段**

在 `apps/api/app/models/llm_call_log.py` 的 `error` 字段之后加：

```python
    # 上下文压缩观测（spec §5.1）：Snapshot 序列化。nullable（未压缩或旧记录为空）。
    context_meta: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
```

并在文件顶部 import 加 `JSONType`：

```python
from app.models.base import Base, IdMixin, JSONType
```

- [ ] **Step 2: 生成迁移文件**

Run: `cd apps/api && uv run alembic revision --autogenerate -m "add llm_call_log context_meta" 2>&1 | tail -5`

检查生成的文件：应包含 `op.add_column('llm_call_logs', sa.Column('context_meta', ...))`。
确认 `down_revision` 指向当前 head `e371fa7db6da`。

- [ ] **Step 3: 手动核对/修正迁移文件**

打开生成的迁移文件，确认 upgrade 含：
```python
op.add_column('llm_call_logs', sa.Column('context_meta', JSONType(), nullable=True))
```
downgrade 含：
```python
op.drop_column('llm_call_logs', 'context_meta')
```

注意：autogenerate 可能用 `postgresql.JSONB()`，需确保用项目的 `JSONType`（`JSONB().with_variant(JSON, "sqlite")`，遵循 GOTCHAS G2）。若 autogenerate 写的是裸 JSONB，手动改成从 `app.models.base` import `JSONType`。

- [ ] **Step 4: 运行迁移验证**

Run: `cd apps/api && uv run alembic upgrade head 2>&1 | tail -3`
Expected: `Running upgrade e371fa7db6da -> <new>, add llm_call_log context_meta`

- [ ] **Step 5: 修改 _log_llm_call 支持 context_meta**

修改 `apps/api/app/api/ai.py:103-131` 的 `_log_llm_call`：

```python
def _log_llm_call(
    db: Session, *,
    user_id, project_id, action: str, model: str, provider: str,
    status: str, tokens=None, duration_ms=None, error=None, context_meta=None,
) -> None:
    """写一条 LLM 调用元数据日志（设计 8.3 红线：只存元数据，不存内容）。

    tokens（断链 C3）：可选 dict {"prompt": int, "completion": int}。
    context_meta（spec §5.1）：可选 dict，上下文压缩 Snapshot 序列化。
    """
    try:
        log = LLMCallLog(
            user_id=user_id,
            project_id=project_id,
            action=action,
            model=model,
            provider=provider,
            token_prompt=tokens.get("prompt") if tokens else None,
            token_completion=tokens.get("completion") if tokens else None,
            duration_ms=duration_ms,
            status=status,
            error=(str(error)[:500] if error else None),
            context_meta=context_meta,
        )
        db.add(log)
        db.commit()
    except Exception:
        db.rollback()
```

- [ ] **Step 6: 运行现有测试确认无回归**

Run: `cd apps/api && uv run pytest tests/test_ai.py tests/test_chat_embedding_resolution.py -v 2>&1 | tail -15`
Expected: 既有测试全 PASS（_log_llm_call 签名变更向后兼容，context_meta 默认 None）

- [ ] **Step 7: 提交**

```bash
git add apps/api/app/models/llm_call_log.py apps/api/alembic/versions/ apps/api/app/api/ai.py
git commit -m "feat(db): LLMCallLog 加 context_meta 字段 —— 上下文压缩观测持久化"
```

---

## Task 7: 接入 orchestrator（章节 chat/generate）

**Files:**
- Modify: `apps/api/app/ai/orchestrator.py:112-169`（astream_chat）
- Modify: `apps/api/app/ai/orchestrator.py:171-231`（astream_generate）
- Test: `apps/api/tests/test_orchestrator_compression.py`

- [ ] **Step 1: 写集成测试**

```python
# apps/api/tests/test_orchestrator_compression.py
"""orchestrator 接入压缩的集成测试（mock agent，验证压缩被调用）。"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.ai.orchestrator import astream_chat
from app.models import Message


def _make_section():
    s = MagicMock()
    s.id = "00000000-0000-0000-0000-000000000001"
    s.project_id = "00000000-0000-0000-0000-000000000002"
    s.key = "technical_problem"
    s.title = "技术问题"
    s.status = "drafting"
    return s


def _make_history(n: int) -> list:
    objs = []
    for i in range(n):
        m = MagicMock()
        m.role = "user" if i % 2 == 0 else "assistant"
        m.content = f"历史消息-{i}" * 5
        objs.append(m)
    return objs


@pytest.mark.asyncio
async def test_astream_chat_compresses_long_history(monkeypatch):
    """35 条历史触发压缩 → mock agent 收到的 messages 含摘要标记。"""
    section = _make_section()
    history = _make_history(35)
    cfg = MagicMock(); cfg.model = "glm-4"; cfg.base_url = "x"; cfg.api_key = "y"

    captured_messages = []

    class FakeAgent:
        async def astream_events(self, payload, version=None):
            captured_messages.extend(payload.get("messages", []))
            yield {"event": "on_chat_model_stream", "data": {"chunk": MagicMock(content="hi")}}

    async def fake_build_agent(*a, **kw):
        return FakeAgent()

    monkeypatch.setattr("app.ai.orchestrator.build_agent", fake_build_agent, raising=False)
    monkeypatch.setattr("app.ai.agent.build_agent", fake_build_agent)
    monkeypatch.setattr("app.ai.intent.classify_intent", lambda x: "info")
    # mock _section_owner
    monkeypatch.setattr("app.ai.orchestrator._section_owner", lambda db, s: None)

    tokens = []
    async for kind, payload in astream_chat(None, section, history, "当前问题", llm_config=cfg):
        if kind == "token":
            tokens.append(payload)

    assert tokens == ["hi"]
    # 压缩应触发：captured_messages 应含「早期对话历史摘要」标记，且条数远少于 36
    contents = [m.get("content", "") if isinstance(m, dict) else getattr(m, "content", "") for m in captured_messages]
    assert any("早期对话历史摘要" in c for c in contents), "长历史应被压缩并含摘要标记"


@pytest.mark.asyncio
async def test_astream_chat_short_history_not_compressed(monkeypatch):
    """5 条历史不触发压缩 → messages 原样透传。"""
    section = _make_section()
    history = _make_history(5)
    cfg = MagicMock(); cfg.model = "glm-4"; cfg.base_url = "x"; cfg.api_key = "y"

    captured_messages = []

    class FakeAgent:
        async def astream_events(self, payload, version=None):
            captured_messages.extend(payload.get("messages", []))
            if False:
                yield {}

    async def fake_build_agent(*a, **kw):
        return FakeAgent()

    monkeypatch.setattr("app.ai.agent.build_agent", fake_build_agent)
    monkeypatch.setattr("app.ai.intent.classify_intent", lambda x: "info")
    monkeypatch.setattr("app.ai.orchestrator._section_owner", lambda db, s: None)

    async for _ in astream_chat(None, section, history, "当前问题", llm_config=cfg):
        pass

    contents = [m.get("content", "") for m in captured_messages]
    assert not any("早期对话历史摘要" in c for c in contents), "短历史不应被压缩"
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd apps/api && uv run pytest tests/test_orchestrator_compression.py -v`
Expected: FAIL（当前 astream_chat 全量灌 history，35 条不会出现摘要标记）

- [ ] **Step 3: 修改 astream_chat 接入压缩**

修改 `apps/api/app/ai/orchestrator.py` 的 `astream_chat`（112-169 行）。把当前的：

```python
    # [L2] 透传历史 + 当前用户输入（spec §3.3.2）
    messages = []
    for msg in history:
        messages.append({"role": msg.role, "content": msg.content})
    messages.append({"role": "user", "content": user_input})
```

替换为：

```python
    # [L2] 透传历史 + 当前用户输入，长历史先压缩（spec §3.3.2 + 压缩 spec）
    import logging
    from app.ai.context_compactor import compress_history

    compressed, snapshot = await compress_history(
        history, user_input, llm_config, scene="chat"
    )
    if snapshot.triggered:
        logging.getLogger(__name__).info(
            "上下文压缩触发 (chat, section=%s): reason=%s %d→%d条 fallback=%s",
            section.id, snapshot.reason, snapshot.original_count,
            snapshot.compressed_count, snapshot.fallback,
        )
    messages = compressed  # compress_history 已含首+摘要+尾+current_input
```

- [ ] **Step 4: 修改 astream_generate 接入压缩**

修改 `astream_generate`（171-231 行）。把当前的：

```python
    # [L2] 透传本章节对话历史（spec §3.3.1）
    messages = []
    for msg in history:
        messages.append({"role": msg.role, "content": msg.content})
    messages.append({"role": "user", "content": instruction})
```

替换为：

```python
    # [L2] 透传历史，长历史先压缩，再 append generate 指令（压缩 spec）
    import logging
    from app.ai.context_compactor import compress_history

    compressed, snapshot = await compress_history(
        history, instruction, llm_config, scene="generate"
    )
    if snapshot.triggered:
        logging.getLogger(__name__).info(
            "上下文压缩触发 (generate, section=%s): reason=%s %d→%d条",
            section.id, snapshot.reason, snapshot.original_count, snapshot.compressed_count,
        )
    messages = compressed  # 已含尾部的 generate instruction
```

- [ ] **Step 5: 运行测试验证通过**

Run: `cd apps/api && uv run pytest tests/test_orchestrator_compression.py -v`
Expected: PASS (2 passed)

- [ ] **Step 6: 运行 orchestrator 相关既有测试确认无回归**

Run: `cd apps/api && uv run pytest tests/test_ai.py tests/test_ai_endpoints_chat_source.py -v 2>&1 | tail -20`
Expected: 既有测试全 PASS（注意：这些走 HTTP 端点，mock 了 LLM；若因 mock 不全报错，需在端点测试的 mock 里补上 get_llm 的摘要路径，或确认短历史不触发压缩）

- [ ] **Step 7: 提交**

```bash
git add apps/api/app/ai/orchestrator.py apps/api/tests/test_orchestrator_compression.py
git commit -m "feat(ai): 章节对话/生成接入上下文压缩 —— astream_chat/generate"
```

---

## Task 8: 接入 init_orchestrator（项目初始化助手）

**Files:**
- Modify: `apps/api/app/ai/init_orchestrator.py:52-61`（_build_init_chat_messages）
- Modify: `apps/api/app/ai/init_orchestrator.py:77-94`（_build_section_generate_messages）
- Test: `apps/api/tests/test_orchestrator_compression.py`

- [ ] **Step 1: 写失败测试**

```python
# 追加到 test_orchestrator_compression.py
from app.ai.init_orchestrator import astream_init_chat, _build_init_chat_messages


@pytest.mark.asyncio
async def test_astream_init_chat_compresses_long_history(monkeypatch):
    """init 助手 35 条历史触发压缩。"""
    history = _make_history(35)
    cfg = MagicMock(); cfg.model = "glm-4"; cfg.base_url = "x"; cfg.api_key = "y"

    captured_messages = []

    async def fake_astream_llm(messages, *, llm_config, usage_sink=None):
        captured_messages.extend(messages)
        yield "tok"

    monkeypatch.setattr("app.ai.init_orchestrator.astream_llm", fake_astream_llm)

    tokens = []
    async for t in astream_init_chat(history, "当前问题", llm_config=cfg):
        tokens.append(t)

    assert tokens == ["tok"]
    contents = [getattr(m, "content", "") for m in captured_messages]
    assert any("早期对话历史摘要" in c for c in contents), "init 长历史应被压缩"


@pytest.mark.asyncio
async def test_astream_init_chat_short_history_not_compressed(monkeypatch):
    """init 助手 5 条历史不触发压缩。"""
    history = _make_history(5)
    cfg = MagicMock(); cfg.model = "glm-4"; cfg.base_url = "x"; cfg.api_key = "y"

    captured_messages = []

    async def fake_astream_llm(messages, *, llm_config, usage_sink=None):
        captured_messages.extend(messages)
        if False:
            yield ""

    monkeypatch.setattr("app.ai.init_orchestrator.astream_llm", fake_astream_llm)

    async for _ in astream_init_chat(history, "当前问题", llm_config=cfg):
        pass

    contents = [getattr(m, "content", "") for m in captured_messages]
    assert not any("早期对话历史摘要" in c for c in contents)
```

- [ ] **Step 2: 运行测试验证失败**

Run: `cd apps/api && uv run pytest tests/test_orchestrator_compression.py -k init -v`
Expected: FAIL（当前 _build_init_chat_messages 全量透传）

- [ ] **Step 3: 改造 _build_init_chat_messages 为异步 + 接入压缩**

把 `init_orchestrator.py:52-61` 的 `_build_init_chat_messages` 改为异步，并在 `astream_init_chat`（64-74 行）调用：

```python
async def _build_init_chat_messages(
    history: list[Message], user_input: str, llm_config
) -> list:
    """装配 init chat 消息：INIT_SYSTEM_PROMPT + 压缩后历史。

    历史先经 compress_history 压缩（压缩 spec），再转 LangChain 消息类型。
    """
    from app.ai.context_compactor import compress_history

    compressed, snapshot = await compress_history(
        history, user_input, llm_config, scene="init"
    )
    if snapshot.triggered:
        import logging
        logging.getLogger(__name__).info(
            "上下文压缩触发 (init chat): reason=%s %d→%d条",
            snapshot.reason, snapshot.original_count, snapshot.compressed_count,
        )

    messages: list = [SystemMessage(content=INIT_SYSTEM_PROMPT)]
    for m in compressed:
        if m["role"] == "user":
            messages.append(HumanMessage(content=m["content"]))
        else:
            messages.append(AIMessage(content=m["content"]))
    return messages
```

修改 `astream_init_chat`（64-74 行）调用处：

```python
async def astream_init_chat(
    history: list[Message], user_input: str,
    *, llm_config: ResolvedChatConfig, usage_sink: dict | None = None,
) -> AsyncIterator[str]:
    """项目初始化对话：流式回复用户，逐 token yield 文本。"""
    messages = await _build_init_chat_messages(history, user_input, llm_config)
    async for token in astream_llm(messages, llm_config=llm_config, usage_sink=usage_sink):
        yield token
```

- [ ] **Step 4: 改造 _build_section_generate_messages 同样接入压缩**

把 `init_orchestrator.py:77-94` 改为异步 + 压缩：

```python
async def _build_section_generate_messages(
    section: Section, history: list[Message], llm_config,
) -> list:
    """装配单章生成消息：INIT_SYSTEM_PROMPT + 压缩历史 + 本章生成指令。"""
    from app.ai.context_compactor import compress_history

    instruction = build_generate_instruction(section)
    compressed, snapshot = await compress_history(
        history, instruction, llm_config, scene="init_generate"
    )
    if snapshot.triggered:
        import logging
        logging.getLogger(__name__).info(
            "上下文压缩触发 (init generate, section=%s): reason=%s %d→%d条",
            section.key, snapshot.reason, snapshot.original_count, snapshot.compressed_count,
        )

    messages: list = [SystemMessage(content=INIT_SYSTEM_PROMPT)]
    for m in compressed:
        if m["role"] == "user":
            messages.append(HumanMessage(content=m["content"]))
        else:
            messages.append(AIMessage(content=m["content"]))
    return messages
```

修改 `astream_init_generate`（131-141 行附近）里调用 `_build_section_generate_messages` 的地方：

```python
            messages = await _build_section_generate_messages(section, history, llm_config)
```

- [ ] **Step 5: 运行测试验证通过**

Run: `cd apps/api && uv run pytest tests/test_orchestrator_compression.py -v`
Expected: PASS (4 passed)

- [ ] **Step 6: 运行 init 相关既有测试确认无回归**

Run: `cd apps/api && uv run pytest tests/ -k init -v 2>&1 | tail -20`
Expected: 既有 init 测试 PASS（若因 _build_* 改异步导致端点调用报错，需确认端点已 await）

- [ ] **Step 7: 检查 init_assistant.py 端点的调用点已 await**

Run: `cd apps/api && grep -n "_build_init_chat_messages\|_build_section_generate_messages\|astream_init_chat\|astream_init_generate" app/api/init_assistant.py`
Expected: 若有直接调用 `_build_*` 的地方，确认已加 `await`。

- [ ] **Step 8: 提交**

```bash
git add apps/api/app/ai/init_orchestrator.py apps/api/tests/test_orchestrator_compression.py
git commit -m "feat(ai): 项目初始化助手接入上下文压缩 —— init chat/generate"
```

---

## Task 9: 关闭 deepagents 默认 SummarizationMiddleware（路径A）

**Files:**
- Modify: `apps/api/app/ai/agent.py:114-121`

- [ ] **Step 1: 核实 deepagents 的 excluded_middleware API**

Run: `cd apps/api && uv run python -c "import deepagents; help(deepagents.create_deep_agent)" 2>&1 | grep -iA3 "middleware"`

检查 `create_deep_agent` 签名是否有 `excluded_middleware` 参数，以及 SummarizationMiddleware 的确切类名/标识。

若无 `excluded_middleware` 参数，查源码找替代方式：
```bash
cd apps/api && uv run python -c "import deepagents, inspect; print(inspect.getsourcefile(deepagents.create_deep_agent))"
```
然后读该文件找中间件注册处，确认如何排除。

- [ ] **Step 2: 根据核实结果修改 build_agent**

如果支持 `excluded_middleware`，修改 `agent.py:114-121`：

```python
    agent = create_deep_agent(
        model=llm,
        system_prompt=system_prompt,
        tools=create_agent_tools(db, user_id),
        skills=skill_sources if skill_sources else None,
        backend=backend,
        store=store,
        excluded_middleware=["SummarizationMiddleware"],  # 用自己的压缩，避免双重压缩（spec §6.1）
    )
```

**若不支持 `excluded_middleware`（回退方案 V1）**：保留库默认中间件不动，在 `build_agent` 加注释说明「库默认 + 天工预处理」并存，且在 commit message 注明此限制。这是可接受的——天工压缩在前、库中间件在已压缩的更短历史上几乎不会再触发。

- [ ] **Step 3: 运行 agent 相关测试确认无回归**

Run: `cd apps/api && uv run pytest tests/test_agent_factory.py tests/test_agent_loop_expire.py -v 2>&1 | tail -15`
Expected: PASS（若 excluded_middleware 参数不被识别会报 TypeError，则回到回退方案）

- [ ] **Step 4: 提交**

```bash
git add apps/api/app/ai/agent.py
git commit -m "feat(ai): 关闭 deepagents 默认 SummarizationMiddleware —— 避免与天工压缩双重压缩"
```
（若用回退方案，commit message 改为 `docs(ai): deepagents 中间件无法排除，保留库默认+天工预处理并存`）

---

## Task 10: 全量回归 + 文档更新

- [ ] **Step 1: 全量测试**

Run: `cd apps/api && uv run pytest 2>&1 | tail -15`
Expected: 全部 PASS（含新增 23+4 个测试 + 既有 36+ 个测试）

- [ ] **Step 2: 迁移幂等验证**

Run: `cd apps/api && uv run alembic downgrade -1 && uv run alembic upgrade head 2>&1 | tail -5`
Expected: downgrade 再 upgrade 成功，context_meta 列正确增删

- [ ] **Step 3: 更新 GOTCHAS.md（记录新踩坑/约定）**

在 `docs/GOTCHAS.md` 适当位置加一条（如有的话），例如：
- 若 deepagents 不支持 excluded_middleware → 记录回退方案
- 若 _build_* 改异步导致端点需 await → 记录异步传染

- [ ] **Step 4: 提交**

```bash
git add docs/GOTCHAS.md
git commit -m "docs: 上下文压缩相关踩坑记录"
```

---

## 验证清单（实现完成后手动确认）

- [ ] 长对话（>30 条）场景：压缩触发，日志可见 `上下文压缩触发`，后台 LLMCallLog.context_meta 有 snapshot
- [ ] 短对话场景：不触发，行为不变
- [ ] 摘要 LLM 失败场景（临时关掉 key）：降级硬截断，对话不崩，snapshot.fallback=True
- [ ] init 助手多章生成：每章历史被压缩，token 消耗下降
- [ ] Message 表原始数据完整（压缩不污染）
