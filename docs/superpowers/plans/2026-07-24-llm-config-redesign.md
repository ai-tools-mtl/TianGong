# LLM 配置改造 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为天工的 LLM 配置加入 provider 模板预设、增强测试连接（chat+embedding 双测、admin 全局也测）、拉取模型列表三大功能，并把 admin 全局配置页和用户自定义配置页用 Apple Liquid Glass 的「unified panel + 内联展开」语言统一。

**Architecture:** 后端新增静态模板数据模块 + 在 `llm_config_service` 加 `test_llm_connection`/`list_provider_models` 两个纯函数（httpx 直连，不落库），新增/改造 4 个端点（模板列表、用户测试、用户拉模型、admin 测试、admin 拉模型）；抽出 `_friendly_llm_error` 到共享模块。前端新建 `components/llm-config/` 共享组件（5 个），重构 `/settings` 与 `/admin/console/llm` 两个页面，去掉顶部 radio、改内联展开、接入模板/测试/拉模型。附带修复 `conversation_service` 的 `get_llm` 调用 bug。

**Tech Stack:** FastAPI + SQLAlchemy 2.0（后端）；Next.js + React Query + shadcn/ui 3.x（前端）；httpx（拉模型直连）；pytest + SQLite 内存库（测试）。

**Spec:** `docs/superpowers/specs/2026-07-24-llm-config-redesign-design.md`

---

## 文件结构

### 后端（apps/api/）
| 文件 | 职责 | 动作 |
|---|---|---|
| `app/ai/llm_errors.py` | 共享：`friendly_llm_error(e)`（从 `api/ai.py` 抽出） | 新建 |
| `app/services/llm_provider_templates.py` | 静态 provider 模板数据 + `get_template(id)` | 新建 |
| `app/services/llm_config_service.py` | 加 `test_llm_connection`、`list_provider_models` 两个函数 | 改 |
| `app/api/ai.py` | `_friendly_llm_error` 改为从 `app.ai.llm_errors` import | 改 |
| `app/api/settings.py` | 改造 `test_my_llm` 返回结构；新增 `/settings/llm/templates`、`/settings/llm/models` | 改 |
| `app/api/admin/console.py` | 新增 `/admin/llm-config/test`、`/admin/llm-config/models` | 改 |
| `app/services/conversation_service.py` | F1：修 `get_llm` 调用 bug | 改 |
| `tests/test_llm_errors.py` | 友好错误映射测试 | 新建 |
| `tests/test_llm_provider_templates.py` | 模板完整性 + `get_template` | 新建 |
| `tests/test_llm_test_connection.py` | `test_llm_connection` mock 测试 | 新建 |
| `tests/test_llm_list_models.py` | `list_provider_models` mock 测试 | 新建 |
| `tests/test_llm_config_endpoints.py` | 端点级（templates/models/test，含 admin） | 新建 |
| `tests/test_conversation_title.py` | F1 回归 | 新建 |

### 前端（apps/web/src/）
| 文件 | 职责 | 动作 |
|---|---|---|
| `components/ui/switch.tsx` | 手写 pill 式开关（shadcn CLI 装不了，GOTCHAS F8） | 新建 |
| `components/llm-config/ProviderTemplatePicker.tsx` | 模板 chip 条 | 新建 |
| `components/llm-config/ModelSelectInput.tsx` | 下拉+手输模型输入 | 新建 |
| `components/llm-config/TestResultBadge.tsx` | 测试结果四态展示 | 新建 |
| `components/llm-config/LLMConfigEditPanel.tsx` | 内联展开编辑/新增面板 | 新建 |
| `components/llm-config/LLMConfigRow.tsx` | 列表行（含设为默认/测试/编辑/删除） | 新建 |
| `lib/api.ts` | 加 5 个端点 client 函数 | 改 |
| `types/api.ts` | 加 `ProviderTemplate`/`TestConnectionResult`/`ListModelsResult` 类型 | 改 |
| `lib/queries.ts` | 加 `useProviderTemplates` 等 React Query hooks | 改 |
| `lib/llm-source.ts` | 加 `isGlobalDefault`/`setGlobalDefault` | 改 |
| `app/(app)/settings/page.tsx` | 去 SourceSelector，接 LLMConfigRow + EditPanel | 改 |
| `app/(app)/admin/console/llm/page.tsx` | enabled 换 Switch，接 EditPanel，加测试/拉模型 | 改 |

---

## Task 1: 抽出共享 `friendly_llm_error`

**Files:**
- Create: `apps/api/app/ai/llm_errors.py`
- Modify: `apps/api/app/api/ai.py:97-119`
- Test: `apps/api/tests/test_llm_errors.py`

- [ ] **Step 1: 写失败测试**

Create `apps/api/tests/test_llm_errors.py`:

```python
"""friendly_llm_error 友好映射测试（从 api/ai.py 抽出，供 test_llm_connection 复用）。"""

import pytest

from app.ai.llm_errors import friendly_llm_error


def _exc(msg: str) -> Exception:
    return Exception(msg)


def test_model_empty_1214():
    assert "模型名" in friendly_llm_error(_exc("1214 model code cannot be empty"))


def test_model_empty_value_error_wording():
    """get_llm 抛的 ValueError 含「缺少 model」，应映射到「模型名」提示。"""
    assert "模型名" in friendly_llm_error(ValueError("LLM 配置缺少 model"))


def test_bad_key_1002():
    assert "API Key" in friendly_llm_error(_exc("1002 Authorization failed"))


def test_bad_key_401():
    assert "API Key" in friendly_llm_error(_exc("401 Invalid API Key"))


def test_timeout():
    assert "超时" in friendly_llm_error(_exc("Request timed out after 30s"))


def test_connection_error():
    assert "连接" in friendly_llm_error(_exc("Connection refused unreachable host"))


def test_unmatched_keeps_original_truncated():
    long = "x" * 500
    out = friendly_llm_error(_exc(long))
    assert out == long[:200]


def test_unmatched_short_kept_as_is():
    assert friendly_llm_error(_exc("some weird error")) == "some weird error"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_llm_errors.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.ai.llm_errors'`

- [ ] **Step 3: 新建共享模块**

Create `apps/api/app/ai/llm_errors.py`:

```python
"""LLM 错误友好化（共享）。

从 app/api/ai.py 抽出，供 SSE 端点（api/ai.py）与测试连接（llm_config_service.test_llm_connection）共用，
避免逻辑分裂。覆盖智谱 GLM / OpenAI 兼容协议常见错误码：
- 1214 / "model code cannot be empty" / get_llm 的 ValueError「缺少 model」→ 提示补模型名
- 1002 / 401 / Authorization / Invalid API Key → 提示查 Key
- 超时 / 连接 → 提示网络
未匹配保留 str(e)（截断 200），不丢信息。
"""


def friendly_llm_error(e: Exception) -> str:
    """把 LLM provider 原始异常转成中文友好提示。"""
    msg = str(e)
    # 1214：model 为空（含上游 get_llm 的 ValueError「缺少 model」）
    if "1214" in msg or "model code cannot be empty" in msg or "缺少 model" in msg:
        return "LLM 配置缺少模型名，请前往设置补全「模型」字段"
    # 1002 / key 非法 / 401
    if "1002" in msg or "Authorization" in msg or "API Key" in msg or "Invalid API Key" in msg:
        return "API Key 无效或已过期，请前往设置检查密钥"
    # 超时 / 连接
    if "timed out" in msg.lower() or "timeout" in msg.lower():
        return "LLM 请求超时，请稍后重试"
    if "connection" in msg.lower() or "unreachable" in msg.lower():
        return "无法连接 LLM 服务，请检查网络或 base_url"
    return msg[:200]
```

- [ ] **Step 4: 让 `api/ai.py` 复用共享函数**

Modify `apps/api/app/api/ai.py` — replace lines 97-119 (the entire `def _friendly_llm_error` function body) with a thin wrapper that re-exports from the shared module:

Replace:
```python
def _friendly_llm_error(e: Exception) -> str:
    """把 LLM provider 原始异常（晦涩英文）转成中文友好提示（1214 修复闸 4）。

    覆盖智谱 GLM / OpenAI 兼容协议的常见错误码：
    - 1214 model 空 → 提示补模型名
    - 1002 / 401 key 无效 → 提示查 API Key
    - 超时 / 连接 → 提示网络
    未匹配的错误保留 str(e)（截断 200 字符），不丢信息。
    """
    msg = str(e)
    # 1214：model 为空（含上游 get_llm 的 ValueError 也归到"缺模型"语义）
    if "1214" in msg or "model code cannot be empty" in msg or "缺少 model" in msg:
        return "LLM 配置缺少模型名，请前往设置补全「模型」字段"
    # 1002 / key 非法 / 401
    if "1002" in msg or "Authorization" in msg or "API Key" in msg or "Invalid API Key" in msg:
        return "API Key 无效或已过期，请前往设置检查密钥"
    # 超时 / 连接
    if "timed out" in msg.lower() or "timeout" in msg.lower():
        return "LLM 请求超时，请稍后重试"
    if "connection" in msg.lower() or "unreachable" in msg.lower():
        return "无法连接 LLM 服务，请检查网络或 base_url"
    # 未匹配：保留原文（截断），不丢信息
    return msg[:200]
```

With:
```python
from app.ai.llm_errors import friendly_llm_error


def _friendly_llm_error(e: Exception) -> str:
    """友好化 LLM 异常。实现已抽到 app.ai.llm_errors（供 test_llm_connection 共用）。"""
    return friendly_llm_error(e)
```

(把 `from app.ai.llm_errors import friendly_llm_error` 放在 `_friendly_llm_error` 正上方即可，或合并到文件顶部的 import 区——只要在函数被调用前可解析。简单起见放函数正上方。)

- [ ] **Step 5: 跑测试确认通过 + 回归**

Run: `cd apps/api && uv run pytest tests/test_llm_errors.py tests/test_llm.py -v`
Expected: PASS（新测试全绿；现有 `test_llm.py` 不受影响）。

- [ ] **Step 6: 提交**

```bash
cd apps/api && git add app/ai/llm_errors.py app/api/ai.py tests/test_llm_errors.py
git commit -m "refactor(ai): 抽出 friendly_llm_error 到共享模块（供 test_llm_connection 复用）"
```

---

## Task 2: provider 模板静态数据

**Files:**
- Create: `apps/api/app/services/llm_provider_templates.py`
- Test: `apps/api/tests/test_llm_provider_templates.py`

- [ ] **Step 1: 写失败测试**

Create `apps/api/tests/test_llm_provider_templates.py`:

```python
"""provider 模板静态数据测试。"""

from app.services.llm_provider_templates import PROVIDER_TEMPLATES, get_template, ProviderTemplate


def test_templates_non_empty():
    assert len(PROVIDER_TEMPLATES) >= 6


def test_each_template_has_required_fields():
    for t in PROVIDER_TEMPLATES:
        assert t.id, f"{t} 缺 id"
        assert t.name, f"{t.id} 缺 name"
        assert t.models_endpoint, f"{t.id} 缺 models_endpoint"
        # base_url / default_model 对 custom 模板可为空，其余必填
        if t.id != "custom":
            assert t.base_url, f"{t.id} 缺 base_url"
            assert t.default_model, f"{t.id} 缺 default_model"


def test_ids_unique():
    ids = [t.id for t in PROVIDER_TEMPLATES]
    assert len(ids) == len(set(ids))


def test_custom_template_present():
    """custom 模板必须存在（前端「自定义」入口）。"""
    assert get_template("custom") is not None


def test_zhipu_template_fields():
    t = get_template("zhipu")
    assert t is not None
    assert "bigmodel" in t.base_url
    assert t.default_embedding_model == "embedding-3"
    assert t.models_endpoint == "/v1/models"


def test_ollama_uses_tags_endpoint():
    t = get_template("ollama")
    assert t is not None
    assert t.models_endpoint == "/api/tags"


def test_get_template_unknown_returns_none():
    assert get_template("nonexistent") is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_llm_provider_templates.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.llm_provider_templates'`

- [ ] **Step 3: 实现模板模块**

Create `apps/api/app/services/llm_provider_templates.py`:

```python
"""LLM provider 模板预设（静态数据）。

供前端「添加配置」时选择模板自动填 base_url + 默认模型。决策 D2：放后端而非前端硬编码，
便于按部署环境注入不同模板集（内网常需自定义中转网关），且 base_url/默认模型可随供应商调整统一改一处。

每条模板的 models_endpoint 决定 list_provider_models 走 /v1/models 还是 /api/tags（Ollama）。
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderTemplate:
    id: str                                  # "zhipu" / "openai" / "deepseek" / "openrouter" / "moonshot" / "ollama" / "custom"
    name: str                                # 展示名
    base_url: str                            # 默认 base_url（custom 为空）
    default_model: str                       # 默认 chat 模型名（custom 为空）
    default_embedding_model: str | None      # 默认 embedding 模型名（无则 None）
    models_endpoint: str                     # 拉模型相对路径：/v1/models 或 /api/tags（Ollama）
    docs_url: str | None                     # 文档/官网链接（卡片「如何获取 Key」）
    note: str | None                         # 提示文案


PROVIDER_TEMPLATES: tuple[ProviderTemplate, ...] = (
    ProviderTemplate(
        id="zhipu", name="智谱 GLM",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        default_model="glm-4-plus",
        default_embedding_model="embedding-3",
        models_endpoint="/v1/models",
        docs_url="https://open.bigmodel.cn",
        note="智谱开放平台，需在控制台开通对应模型",
    ),
    ProviderTemplate(
        id="deepseek", name="DeepSeek",
        base_url="https://api.deepseek.com",
        default_model="deepseek-chat",
        default_embedding_model=None,
        models_endpoint="/v1/models",
        docs_url="https://platform.deepseek.com",
        note=None,
    ),
    ProviderTemplate(
        id="openai", name="OpenAI",
        base_url="https://api.openai.com/v1",
        default_model="gpt-4o-mini",
        default_embedding_model="text-embedding-3-small",
        models_endpoint="/v1/models",
        docs_url="https://platform.openai.com/api-keys",
        note=None,
    ),
    ProviderTemplate(
        id="openrouter", name="OpenRouter",
        base_url="https://openrouter.ai/api/v1",
        default_model="openai/gpt-4o-mini",
        default_embedding_model=None,
        models_endpoint="/v1/models",
        docs_url="https://openrouter.ai/keys",
        note=None,
    ),
    ProviderTemplate(
        id="moonshot", name="Moonshot Kimi",
        base_url="https://api.moonshot.cn/v1",
        default_model="moonshot-v1-8k",
        default_embedding_model=None,
        models_endpoint="/v1/models",
        docs_url="https://platform.moonshot.cn",
        note=None,
    ),
    ProviderTemplate(
        id="ollama", name="Ollama（本地）",
        base_url="http://localhost:11434",
        default_model="qwen2.5:7b",
        default_embedding_model="nomic-embed-text",
        models_endpoint="/api/tags",
        docs_url="https://ollama.com",
        note="本地部署，无需 API Key（Key 字段任意填）",
    ),
    ProviderTemplate(
        id="custom", name="自定义（OpenAI 兼容）",
        base_url="",
        default_model="",
        default_embedding_model=None,
        models_endpoint="/v1/models",
        docs_url=None,
        note="填写你的 OpenAI 兼容端点",
    ),
)

_BY_ID: dict[str, ProviderTemplate] = {t.id: t for t in PROVIDER_TEMPLATES}


def get_template(template_id: str) -> ProviderTemplate | None:
    """按 id 取模板，未知返回 None。"""
    return _BY_ID.get(template_id)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_llm_provider_templates.py -v`
Expected: PASS（7 测试全绿）。

- [ ] **Step 5: 提交**

```bash
cd apps/api && git add app/services/llm_provider_templates.py tests/test_llm_provider_templates.py
git commit -m "feat(llm): provider 模板预设静态数据（7 个：智谱/DS/OpenAI/OpenRouter/Moonshot/Ollama/自定义）"
```

---

## Task 3: `list_provider_models` — 拉取模型列表（service）

**Files:**
- Modify: `apps/api/app/services/llm_config_service.py`（末尾追加函数）
- Modify: `apps/api/pyproject.toml`（httpx 提为 runtime 依赖）
- Test: `apps/api/tests/test_llm_list_models.py`

- [ ] **Step 1: 把 httpx 提为 runtime 依赖**

Modify `apps/api/pyproject.toml` — in the `dependencies = [...]` list (lines 6-33), add `"httpx>=0.27.0",` after the `"cryptography>=43.0.0",` line (line 17):

```toml
    "cryptography>=43.0.0",
    "httpx>=0.27.0",
    "python-multipart>=0.0.12",
```

(它原先只在 dev extra。决策 D4：service 层 `list_provider_models` 用 httpx 直连，故提为 runtime 依赖。)

Then run: `cd apps/api && uv sync`（同步 lockfile）。

- [ ] **Step 2: 写失败测试**

Create `apps/api/tests/test_llm_list_models.py`:

```python
"""list_provider_models 测试（mock httpx，不真实联网）。"""

from unittest.mock import MagicMock, patch

import httpx

from app.services import llm_config_service


def _ok_response(status_code=200, json_data=None):
    """构造假的 httpx.Response。"""
    r = MagicMock(spec=httpx.Response)
    r.status_code = status_code
    r.json.return_value = json_data or {}
    return r


def test_openai_compatible_format():
    """OpenAI 兼容 /v1/models：{data:[{id:...}]} → 取 id。"""
    fake = _ok_response(200, {"data": [
        {"id": "glm-4-plus"}, {"id": "glm-4-flash"}, {"id": "embedding-3"},
    ]})
    with patch("app.services.llm_config_service.httpx.get", return_value=fake):
        res = llm_config_service.list_provider_models(
            base_url="https://open.bigmodel.cn/api/paas/v4",
            api_key="sk-test",
            provider_template_id="zhipu",
        )
    assert res["error"] is None
    assert res["models"] == ["embedding-3", "glm-4-flash", "glm-4-plus"]  # 去重+排序
    assert res["truncated"] is False


def test_ollama_tags_format():
    """Ollama /api/tags：{models:[{name:...}]} → 取 name。"""
    fake = _ok_response(200, {"models": [
        {"name": "qwen2.5:7b"}, {"name": "nomic-embed-text"},
    ]})
    with patch("app.services.llm_config_service.httpx.get", return_value=fake):
        res = llm_config_service.list_provider_models(
            base_url="http://localhost:11434",
            api_key="x",
            provider_template_id="ollama",
        )
    assert res["error"] is None
    assert "qwen2.5:7b" in res["models"]
    assert "nomic-embed-text" in res["models"]


def test_default_to_v1_models_when_no_template():
    """未给 template_id 时默认走 /v1/models。"""
    fake = _ok_response(200, {"data": [{"id": "m1"}]})
    with patch("app.services.llm_config_service.httpx.get", return_value=fake) as m:
        llm_config_service.list_provider_models(
            base_url="https://x.com/v1", api_key="k", provider_template_id=None,
        )
    called_url = m.call_args.args[0]
    assert called_url.endswith("/v1/models")


def test_401_returns_error_not_raise():
    fake = _ok_response(401, {"error": "bad key"})
    with patch("app.services.llm_config_service.httpx.get", return_value=fake):
        res = llm_config_service.list_provider_models(
            base_url="https://x.com/v1", api_key="bad", provider_template_id=None,
        )
    assert res["models"] == []
    assert "API Key" in res["error"] or "401" in res["error"]


def test_connection_error_returns_error():
    with patch("app.services.llm_config_service.httpx.get",
               side_effect=httpx.ConnectError("refused")):
        res = llm_config_service.list_provider_models(
            base_url="https://down.example.com", api_key="k", provider_template_id=None,
        )
    assert res["models"] == []
    assert "连接" in res["error"]


def test_timeout_returns_error():
    with patch("app.services.llm_config_service.httpx.get",
               side_effect=httpx.TimeoutException("slow")):
        res = llm_config_service.list_provider_models(
            base_url="https://slow.example.com", api_key="k", provider_template_id=None,
        )
    assert res["models"] == []
    assert "超时" in res["error"]


def test_truncation_at_100():
    fake = _ok_response(200, {"data": [{"id": f"m{i}"} for i in range(150)]})
    with patch("app.services.llm_config_service.httpx.get", return_value=fake):
        res = llm_config_service.list_provider_models(
            base_url="https://x.com/v1", api_key="k", provider_template_id=None,
        )
    assert len(res["models"]) == 100
    assert res["truncated"] is True


def test_dedup():
    fake = _ok_response(200, {"data": [{"id": "a"}, {"id": "a"}, {"id": "b"}]})
    with patch("app.services.llm_config_service.httpx.get", return_value=fake):
        res = llm_config_service.list_provider_models(
            base_url="https://x.com/v1", api_key="k", provider_template_id=None,
        )
    assert res["models"] == ["a", "b"]


def test_unexpected_format_returns_error():
    fake = _ok_response(200, {"weird": "shape"})
    with patch("app.services.llm_config_service.httpx.get", return_value=fake):
        res = llm_config_service.list_provider_models(
            base_url="https://x.com/v1", api_key="k", provider_template_id=None,
        )
    assert res["models"] == []
    assert "格式" in res["error"] or "解析" in res["error"]
```

- [ ] **Step 3: 跑测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_llm_list_models.py -v`
Expected: FAIL with `AttributeError: module 'app.services.llm_config_service' has no attribute 'list_provider_models'`（以及 `httpx` 未在该模块 import）。

- [ ] **Step 4: 实现 `list_provider_models`**

Modify `apps/api/app/services/llm_config_service.py` — add `import httpx` near the top (after line 17 `from sqlalchemy import select`), and append this function at the very end of the file (after `_mask_key`):

```python
import httpx

# ...（文件其余部分不变）...


# ── 拉取 provider 模型列表（决策 D4：httpx 直连，不绕 LangChain）──

_LIST_MODELS_MAX = 100
_LIST_MODELS_TIMEOUT = 15.0


def list_provider_models(
    db: Session | None = None, *,  # db 保留位置以兼容 service 风格，本函数不用
    base_url: str,
    api_key: str,
    provider_template_id: str | None = None,
) -> dict:
    """调 provider 的模型列表端点，返回 {models, truncated, error}。

    - provider_template_id 指向 ollama → GET {base_url}/api/tags，取 models[].name
    - 其余（含 None）→ GET {base_url}/v1/models，取 data[].id（OpenAI 兼容）
    - 去重 + 字母序排序；超过 100 条截断，truncated=True
    - 任何错误（连接/超时/401/格式异常）→ {models:[], error:"友好"}，不抛异常
    """
    from app.services.llm_provider_templates import get_template

    endpoint_path = "/api/tags"
    tpl = get_template(provider_template_id) if provider_template_id else None
    if tpl:
        endpoint_path = tpl.models_endpoint
    base = base_url.rstrip("/")
    url = f"{base}{endpoint_path}"

    try:
        resp = httpx.get(
            url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=_LIST_MODELS_TIMEOUT,
        )
    except httpx.TimeoutException:
        return {"models": [], "truncated": False, "error": "拉取模型超时，请检查网络或端点"}
    except httpx.HTTPError:
        return {"models": [], "truncated": False, "error": f"无法连接到 {base}，请检查 base_url"}

    if resp.status_code == 401 or resp.status_code == 403:
        return {"models": [], "truncated": False, "error": "API Key 无效或无权限（401/403）"}
    if resp.status_code != 200:
        return {"models": [], "truncated": False,
                "error": f"拉取失败：HTTP {resp.status_code}"}

    try:
        body = resp.json()
    except Exception:
        return {"models": [], "truncated": False, "error": "响应非 JSON，无法解析"}

    # OpenAI 兼容：{data:[{id}]}；Ollama：{models:[{name}]}
    raw: list[str] = []
    if isinstance(body, dict) and isinstance(body.get("data"), list):
        raw = [item.get("id") for item in body["data"] if isinstance(item, dict) and item.get("id")]
    elif isinstance(body, dict) and isinstance(body.get("models"), list):
        raw = [item.get("name") for item in body["models"] if isinstance(item, dict) and item.get("name")]
    else:
        return {"models": [], "truncated": False, "error": "响应格式无法解析（期望 data[].id 或 models[].name）"}

    # 去重 + 排序 + 截断
    unique = sorted(set(raw))
    truncated = len(unique) > _LIST_MODELS_MAX
    return {"models": unique[:_LIST_MODELS_MAX], "truncated": truncated, "error": None}
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_llm_list_models.py -v`
Expected: PASS（9 测试全绿）。

- [ ] **Step 6: 提交**

```bash
cd apps/api && git add pyproject.toml uv.lock app/services/llm_config_service.py tests/test_llm_list_models.py
git commit -m "feat(llm): list_provider_models——httpx 直连拉取 provider 模型列表"
```

---

## Task 4: `test_llm_connection` — 增强测试连接（service）

**Files:**
- Modify: `apps/api/app/services/llm_config_service.py`（追加函数）
- Test: `apps/api/tests/test_llm_test_connection.py`

- [ ] **Step 1: 写失败测试**

Create `apps/api/tests/test_llm_test_connection.py`:

```python
"""test_llm_connection 测试（mock ChatOpenAI / OpenAIEmbeddings，不真实联网）。"""

from unittest.mock import MagicMock, patch

from app.services import llm_config_service


def _fake_chat_resp(content="hi there"):
    m = MagicMock()
    m.content = content
    return m


def test_chat_ok_embedding_ok():
    with patch("app.services.llm_config_service.ChatOpenAI") as MC, \
         patch("app.services.llm_config_service.OpenAIEmbeddings") as ME:
        MC.return_value.invoke.return_value = _fake_chat_resp("ok")
        ME.return_value.embed_query.return_value = [0.1] * 128
        res = llm_config_service.test_llm_connection(
            base_url="https://x.com/v1", api_key="sk-good",
            model="m1", embedding_model="emb-1",
        )
    assert res["ok"] is True
    assert res["chat"]["ok"] is True
    assert res["chat"]["error"] is None
    assert res["chat"]["sample"] == "ok"
    assert res["embedding"]["ok"] is True
    assert res["embedding"]["dim"] == 128
    assert res["error"] is None
    # 超时参数透传
    _, kwargs = MC.call_args
    assert kwargs["request_timeout"] == 15


def test_chat_ok_no_embedding_model():
    """embedding_model=None → 只测 chat，embedding 字段为 None。"""
    with patch("app.services.llm_config_service.ChatOpenAI") as MC, \
         patch("app.services.llm_config_service.OpenAIEmbeddings") as ME:
        MC.return_value.invoke.return_value = _fake_chat_resp()
        res = llm_config_service.test_llm_connection(
            base_url="https://x.com/v1", api_key="sk-good",
            model="m1", embedding_model=None,
        )
    assert res["ok"] is True
    assert res["embedding"] is None
    ME.assert_not_called()


def test_chat_fail_embedding_ok():
    """chat 抛异常但 embedding 成功 → ok=False，两者各自报告。"""
    with patch("app.services.llm_config_service.ChatOpenAI") as MC, \
         patch("app.services.llm_config_service.OpenAIEmbeddings") as ME:
        MC.return_value.invoke.side_effect = Exception("1214 model code cannot be empty")
        ME.return_value.embed_query.return_value = [0.1] * 8
        res = llm_config_service.test_llm_connection(
            base_url="https://x.com/v1", api_key="sk-good",
            model="m1", embedding_model="emb-1",
        )
    assert res["ok"] is False
    assert res["chat"]["ok"] is False
    assert "模型名" in res["chat"]["error"]
    assert res["embedding"]["ok"] is True  # embedding 仍独立成功


def test_chat_ok_embedding_fail():
    with patch("app.services.llm_config_service.ChatOpenAI") as MC, \
         patch("app.services.llm_config_service.OpenAIEmbeddings") as ME:
        MC.return_value.invoke.return_value = _fake_chat_resp()
        ME.return_value.embed_query.side_effect = Exception("401 Invalid API Key")
        res = llm_config_service.test_llm_connection(
            base_url="https://x.com/v1", api_key="sk-good",
            model="m1", embedding_model="emb-1",
        )
    assert res["ok"] is False
    assert res["chat"]["ok"] is True
    assert res["embedding"]["ok"] is False
    assert "API Key" in res["embedding"]["error"]


def test_both_fail():
    with patch("app.services.llm_config_service.ChatOpenAI") as MC, \
         patch("app.services.llm_config_service.OpenAIEmbeddings") as ME:
        MC.return_value.invoke.side_effect = Exception("connection refused")
        ME.return_value.embed_query.side_effect = Exception("timed out")
        res = llm_config_service.test_llm_connection(
            base_url="https://x.com/v1", api_key="sk-good",
            model="m1", embedding_model="emb-1",
        )
    assert res["ok"] is False
    assert res["chat"]["ok"] is False
    assert res["embedding"]["ok"] is False


def test_latency_recorded():
    with patch("app.services.llm_config_service.ChatOpenAI") as MC:
        MC.return_value.invoke.return_value = _fake_chat_resp()
        res = llm_config_service.test_llm_connection(
            base_url="https://x.com/v1", api_key="k", model="m1", embedding_model=None,
        )
    assert isinstance(res["chat"]["latency_ms"], int)
    assert res["chat"]["latency_ms"] >= 0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_llm_test_connection.py -v`
Expected: FAIL with `AttributeError: module 'app.services.llm_config_service' has no attribute 'test_llm_connection'`

- [ ] **Step 3: 实现 `test_llm_connection`**

Modify `apps/api/app/services/llm_config_service.py` — add imports near the top (after `import httpx`):

```python
import time
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_core.messages import HumanMessage
```

Then append this function at the end of the file (after `list_provider_models`):

```python
# ── 测试连通性（增强版：chat + embedding 双测）──

_TEST_TIMEOUT = 15


def test_llm_connection(
    db: Session | None = None, *,  # 保留位置兼容 service 风格，本函数不用
    base_url: str,
    api_key: str,
    model: str,
    embedding_model: str | None = None,
) -> dict:
    """测试 LLM 连通性。chat 必测；embedding_model 提供则一并测。不落库、不写 LLMCallLog。

    返回 TestConnectionResult：
      {ok, chat:{ok,latency_ms,sample,error}, embedding:{...}|None, error}
    chat 与 embedding 独立 try/except，互不影响。
    所有错误经 friendly_llm_error 友好化。
    """
    from app.ai.llm_errors import friendly_llm_error

    # ---- chat ----
    chat = {"ok": False, "latency_ms": None, "sample": None, "error": None}
    try:
        llm = ChatOpenAI(
            model=model, base_url=base_url, api_key=api_key,
            request_timeout=_TEST_TIMEOUT,
        )
        t0 = time.perf_counter()
        resp = llm.invoke([HumanMessage(content="hi")])
        chat["latency_ms"] = int((time.perf_counter() - t0) * 1000)
        chat["ok"] = True
        chat["sample"] = (resp.content or "")[:50]
    except Exception as e:
        chat["error"] = friendly_llm_error(e)

    # ---- embedding（仅当 embedding_model 非空）----
    embedding = None
    if embedding_model:
        embedding = {"ok": False, "latency_ms": None, "dim": None, "error": None}
        try:
            emb = OpenAIEmbeddings(
                model=embedding_model, base_url=base_url, api_key=api_key,
                request_timeout=_TEST_TIMEOUT,
            )
            t0 = time.perf_counter()
            vec = emb.embed_query("hi")
            embedding["latency_ms"] = int((time.perf_counter() - t0) * 1000)
            embedding["ok"] = True
            embedding["dim"] = len(vec) if vec else None
        except Exception as e:
            embedding["error"] = friendly_llm_error(e)

    ok = chat["ok"] and (embedding is None or embedding["ok"])
    return {
        "ok": ok,
        "chat": chat,
        "embedding": embedding,
        "error": None if ok else (chat["error"] or (embedding["error"] if embedding else None)),
    }
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_llm_test_connection.py -v`
Expected: PASS（6 测试全绿）。

- [ ] **Step 5: 提交**

```bash
cd apps/api && git add app/services/llm_config_service.py tests/test_llm_test_connection.py
git commit -m "feat(llm): test_llm_connection——chat+embedding 双测、延迟、友好错误、15s 超时"
```

---

## Task 5: 用户侧端点（templates / models / 改造 test）

**Files:**
- Modify: `apps/api/app/api/settings.py:42-49,121-139`
- Test: `apps/api/tests/test_llm_config_endpoints.py`

- [ ] **Step 1: 写失败测试**

Create `apps/api/tests/test_llm_config_endpoints.py`:

```python
"""LLM 配置新端点测试：templates / models / 改造后的 test。"""

from unittest.mock import patch

from app.core.security import hash_password
from app.models import User


def _login_user(client, db_session):
    u = User(username="u1", email="u1@example.com",
             password_hash=hash_password("Pass1234!"), name="U1")
    db_session.add(u); db_session.commit()
    client.post("/api/v1/auth/login", json={"username": "u1", "password": "Pass1234!"})
    return u


# ── GET /settings/llm/templates ──

def test_templates_endpoint_returns_list(client, db_session):
    _login_user(client, db_session)
    res = client.get("/api/v1/settings/llm/templates")
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, list)
    assert len(data) >= 6
    ids = [t["id"] for t in data]
    assert "zhipu" in ids and "custom" in ids and "ollama" in ids
    # 字段齐全
    zhipu = next(t for t in data if t["id"] == "zhipu")
    for k in ("id", "name", "base_url", "default_model", "default_embedding_model",
              "models_endpoint", "docs_url", "note"):
        assert k in zhipu


def test_templates_requires_auth(client):
    res = client.get("/api/v1/settings/llm/templates")
    assert res.status_code in (401, 403)


# ── POST /settings/llm/models ──

def test_models_endpoint_returns_models(client, db_session):
    _login_user(client, db_session)
    with patch("app.api.settings.llm_config_service.list_provider_models") as m:
        m.return_value = {"models": ["m1", "m2"], "truncated": False, "error": None}
        res = client.post("/api/v1/settings/llm/models", json={
            "base_url": "https://x.com/v1", "api_key": "sk-test", "provider_template_id": None,
        })
    assert res.status_code == 200
    assert res.json()["models"] == ["m1", "m2"]


def test_models_endpoint_requires_auth(client):
    res = client.post("/api/v1/settings/llm/models", json={
        "base_url": "https://x.com/v1", "api_key": "k",
    })
    assert res.status_code in (401, 403)


# ── POST /settings/llm/test（改造后返回 TestConnectionResult）──

def test_test_endpoint_new_shape(client, db_session):
    _login_user(client, db_session)
    with patch("app.api.settings.llm_config_service.test_llm_connection") as m:
        m.return_value = {
            "ok": True,
            "chat": {"ok": True, "latency_ms": 50, "sample": "hi", "error": None},
            "embedding": {"ok": True, "latency_ms": 40, "dim": 128, "error": None},
            "error": None,
        }
        res = client.post("/api/v1/settings/llm/test", json={
            "base_url": "https://x.com/v1", "api_key": "sk-test",
            "model": "m1", "embedding_model": "emb",
        })
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["chat"]["ok"] is True
    assert body["embedding"]["dim"] == 128
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_llm_config_endpoints.py -v`
Expected: FAIL（templates/models 端点 404；test 端点返回旧 shape）。

- [ ] **Step 3: 改造 settings.py**

Modify `apps/api/app/api/settings.py`:

3a. 改 `UserLLMTestRequest`（L42-49）——去掉 `provider`，保留 embedding_model（现在真测）：

Replace:
```python
class UserLLMTestRequest(BaseModel):
    """测试 LLM 连通性（不落库）。"""
    provider: str = "custom"
    base_url: str
    api_key: str
    # 1214 修复闸 3：测试连通性也必须有 model（无 model 必报 1214）。
    model: str = Field(..., min_length=1)
    embedding_model: str | None = None
```
With:
```python
class UserLLMTestRequest(BaseModel):
    """测试 LLM 连通性（不落库）。chat 必测；embedding_model 提供则一并测。"""
    base_url: str
    api_key: str
    # 1214 修复闸 3：测试连通性也必须有 model（无 model 必报 1214）。
    model: str = Field(..., min_length=1)
    embedding_model: str | None = None


class ListModelsRequest(BaseModel):
    """拉取 provider 可用模型列表（不落库）。"""
    base_url: str
    api_key: str
    provider_template_id: str | None = None
```

3b. 新增 templates 端点（在 `get_my_grant` 之后、`create_my_llm` 之前插入）：

```python
@router.get("/settings/llm/templates")
def list_llm_templates(current_user: User = Depends(get_current_user)):
    """返回 provider 模板预设列表（添加配置时选模板自动填）。"""
    from app.services.llm_provider_templates import PROVIDER_TEMPLATES
    return [
        {
            "id": t.id, "name": t.name, "base_url": t.base_url,
            "default_model": t.default_model,
            "default_embedding_model": t.default_embedding_model,
            "models_endpoint": t.models_endpoint,
            "docs_url": t.docs_url, "note": t.note,
        }
        for t in PROVIDER_TEMPLATES
    ]


@router.post("/settings/llm/models")
def list_my_provider_models(
    payload: ListModelsRequest,
    current_user: User = Depends(get_current_user),
):
    """拉取 provider 可用模型列表（不落库）。"""
    return llm_config_service.list_provider_models(
        base_url=payload.base_url, api_key=payload.api_key,
        provider_template_id=payload.provider_template_id,
    )
```

3c. 改造 `test_my_llm`（L121-139）——委托给 service 函数：

Replace:
```python
@router.post("/settings/llm/test")
def test_my_llm(
    payload: UserLLMTestRequest,
    current_user: User = Depends(get_current_user),
):
    """测试 LLM 连通性（不存库，直接用传入配置测试）。"""
    try:
        from langchain_core.messages import HumanMessage
        from langchain_openai import ChatOpenAI

        llm = ChatOpenAI(
            model=payload.model,
            base_url=payload.base_url,
            api_key=payload.api_key,
        )
        resp = llm.invoke([HumanMessage(content="hi")])
        return {"ok": True, "response": resp.content[:50]}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}
```
With:
```python
@router.post("/settings/llm/test")
def test_my_llm(
    payload: UserLLMTestRequest,
    current_user: User = Depends(get_current_user),
):
    """测试 LLM 连通性（不存库，直接用传入配置测试 chat + 可选 embedding）。"""
    return llm_config_service.test_llm_connection(
        base_url=payload.base_url, api_key=payload.api_key,
        model=payload.model, embedding_model=payload.embedding_model,
    )
```

- [ ] **Step 4: 跑测试确认通过 + 回归**

Run: `cd apps/api && uv run pytest tests/test_llm_config_endpoints.py tests/test_llm.py tests/test_global_llm_config.py -v`
Expected: PASS（新测试绿；现有测试不受影响——注意 `test_global_llm_config.py` 不涉及 test 端点，安全）。

- [ ] **Step 5: 提交**

```bash
cd apps/api && git add app/api/settings.py tests/test_llm_config_endpoints.py
git commit -m "feat(api): 用户侧 LLM 端点——templates/models/改造 test 返回 TestConnectionResult"
```

---

## Task 6: admin 侧端点（test / models）

**Files:**
- Modify: `apps/api/app/api/admin/console.py`（追加端点 + schema）
- Test: `apps/api/tests/test_llm_config_endpoints.py`（同文件追加 admin 测试）

- [ ] **Step 1: 追加 admin 失败测试**

Append to `apps/api/tests/test_llm_config_endpoints.py`:

```python
# ── admin 端点（/admin/llm-config/test + /admin/llm-config/models）──

def _login_admin(client, db_session):
    a = User(username="admin", email="admin@example.com",
             password_hash=hash_password("Admin1234!"), name="A", role="admin", status="active")
    db_session.add(a); db_session.commit()
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "Admin1234!"})
    return a


def test_admin_test_with_provided_values(client, db_session):
    """admin 用传入值测（保存前预检）。"""
    _login_admin(client, db_session)
    with patch("app.api.admin.console.llm_config_service.test_llm_connection") as m:
        m.return_value = {"ok": True, "chat": {"ok": True, "latency_ms": 10, "sample": "hi", "error": None},
                          "embedding": None, "error": None}
        res = client.post("/api/v1/admin/llm-config/test", json={
            "base_url": "https://x.com/v1", "api_key": "sk-new", "model": "m1",
        })
    assert res.status_code == 200
    assert res.json()["ok"] is True
    m.assert_called_once()
    _, kwargs = m.call_args
    assert kwargs["api_key"] == "sk-new"  # 用传入值


def test_admin_test_with_stored_values(client, db_session):
    """admin 不传值 → 用 SystemSetting 已存的（解密后）测（保存后复检）。"""
    _login_admin(client, db_session)
    # 先存一份全局配置
    from app.core.security import encrypt_value
    from app.models import SystemSetting
    db_session.add(SystemSetting(key="llm_global_config", value={
        "base_url": "https://stored.com/v1",
        "api_key_encrypted": encrypt_value("sk-stored-1234567890"),
        "model": "stored-model",
        "embedding_model": "stored-emb",
    }))
    db_session.commit()

    with patch("app.api.admin.console.llm_config_service.test_llm_connection") as m:
        m.return_value = {"ok": True, "chat": {"ok": True, "latency_ms": 5, "sample": "x", "error": None},
                          "embedding": None, "error": None}
        res = client.post("/api/v1/admin/llm-config/test", json={})  # 空 body
    assert res.status_code == 200
    _, kwargs = m.call_args
    assert kwargs["base_url"] == "https://stored.com/v1"
    assert kwargs["api_key"] == "sk-stored-1234567890"  # 解密后
    assert kwargs["model"] == "stored-model"


def test_admin_test_stored_incomplete_returns_error(client, db_session):
    """已存全局配置不完整（缺 model/api_key）→ 返回友好错误。"""
    _login_admin(client, db_session)
    from app.models import SystemSetting
    db_session.add(SystemSetting(key="llm_global_config", value={"base_url": "https://x.com"}))
    db_session.commit()
    res = client.post("/api/v1/admin/llm-config/test", json={})
    assert res.status_code == 200
    assert res.json()["ok"] is False
    assert "未设置" in res.json()["error"] or "不完整" in res.json()["error"]


def test_admin_test_requires_admin(client, db_session):
    """非 admin → 403。"""
    _login_user(client, db_session)  # 普通用户
    res = client.post("/api/v1/admin/llm-config/test", json={})
    assert res.status_code == 403


def test_admin_models_endpoint(client, db_session):
    _login_admin(client, db_session)
    with patch("app.api.admin.console.llm_config_service.list_provider_models") as m:
        m.return_value = {"models": ["m1"], "truncated": False, "error": None}
        res = client.post("/api/v1/admin/llm-config/models", json={
            "base_url": "https://x.com/v1", "api_key": "sk",
        })
    assert res.status_code == 200
    assert res.json()["models"] == ["m1"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_llm_config_endpoints.py -v -k admin`
Expected: FAIL（端点 404）。

- [ ] **Step 3: 实现 admin 端点**

Modify `apps/api/app/api/admin/console.py` — add a new Pydantic schema after `GlobalLLMSettings` (L33) and two new endpoints after `set_global_llm` (L153).

Add schema (after line 33, the closing of `GlobalLLMSettings`):

```python
class GlobalLLMTestRequest(BaseModel):
    """admin 测试全局配置连通性。
    字段全可选：留空 → 用 SystemSetting 已存的（解密后）测（保存后复检）；
    提供则用传入值测（保存前预检）。
    """
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None
    embedding_model: str | None = None


class ListModelsRequest(BaseModel):
    """拉取 provider 可用模型列表（不落库）。"""
    base_url: str
    api_key: str
    provider_template_id: str | None = None
```

Add endpoints (after `set_global_llm`, ~L153):

```python
@router.post("/admin/llm-config/test")
def test_global_llm(
    payload: GlobalLLMTestRequest,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """测试全局 LLM 配置连通性。

    - 提供完整字段 → 用传入值测（保存前预检）。
    - 字段留空 → 从 SystemSetting 读已存的（api_key 解密）测（保存后复检）。
    """
    from sqlalchemy import select as _select
    from app.core.security import decrypt_value

    base_url = payload.base_url
    api_key = payload.api_key
    model = payload.model
    embedding_model = payload.embedding_model

    # 任一关键字段缺 → 用已存值补全
    if not (base_url and api_key and model):
        cfg = db.scalar(_select(SystemSetting).where(SystemSetting.key == "llm_global_config"))
        stored = cfg.value if cfg else {}
        base_url = base_url or stored.get("base_url", "")
        model = model or stored.get("model", "")
        embedding_model = embedding_model if embedding_model is not None else stored.get("embedding_model")
        enc = stored.get("api_key_encrypted")
        api_key = api_key or (decrypt_value(enc) if enc else "")
        # 仍不完整 → 友好错误（不抛 500）
        if not (base_url and api_key and model):
            return {"ok": False, "chat": {"ok": False, "latency_ms": None, "sample": None,
                                          "error": "全局配置未设置完整"},
                    "embedding": None, "error": "全局配置未设置完整（缺 base_url / api_key / model）"}

    return llm_config_service.test_llm_connection(
        base_url=base_url, api_key=api_key, model=model, embedding_model=embedding_model,
    )


@router.post("/admin/llm-config/models")
def list_global_provider_models(
    payload: ListModelsRequest,
    admin: User = Depends(require_admin),
):
    """admin 拉取 provider 可用模型列表（不落库）。"""
    return llm_config_service.list_provider_models(
        base_url=payload.base_url, api_key=payload.api_key,
        provider_template_id=payload.provider_template_id,
    )
```

(注：`SystemSetting` 已在 console.py 通过 `app.models` 导入？—— 检查：line 19 `from app.models import AuditLog, User`。需追加 `SystemSetting`。)

实际上需把 line 19 改为：
```python
from app.models import AuditLog, SystemSetting, User
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_llm_config_endpoints.py -v`
Expected: PASS（全部 14 测试绿）。

- [ ] **Step 5: 提交**

```bash
cd apps/api && git add app/api/admin/console.py tests/test_llm_config_endpoints.py
git commit -m "feat(api): admin 全局 LLM 测试端点（支持传入值/已存值两种模式）+ admin 拉模型端点"
```

---

## Task 7: F1 修复 — `conversation_service.summarize_conversation_title`

**Files:**
- Modify: `apps/api/app/services/conversation_service.py:8-51`
- Test: `apps/api/tests/test_conversation_title.py`

- [ ] **Step 1: 写失败测试**

Create `apps/api/tests/test_conversation_title.py`:

```python
"""summarize_conversation_title 回归测试（F1：修复 get_llm 调用 bug）。

原 bug：get_llm(**{base_url,api_key,model}) 传错参数（get_llm 期望 ResolvedLLMConfig），
TypeError 被 except Exception 吞掉，标题摘要始终 fallback。
"""

from unittest.mock import MagicMock, patch

from app.services.conversation_service import summarize_conversation_title
from app.services.llm_config_service import ResolvedLLMConfig


def _cfg():
    return ResolvedLLMConfig(
        base_url="https://x.com/v1", api_key="sk-test",
        model="glm-4-flash", embedding_model=None, source="user",
    )


def test_title_calls_llm_when_config_provided(db_session):
    """提供 llm_config → 真正调 get_llm 并用其返回值。"""
    fake_resp = MagicMock()
    fake_resp.content = "专利交底书撰写"
    conv = MagicMock()  # conversation 对象本身在本函数未被使用（只取首条消息）
    with patch("app.services.conversation_service.get_llm") as m_get:
        m_get.return_value.invoke.return_value = fake_resp
        title = summarize_conversation_title(
            db_session, conv, "帮我写一份关于新型电机的交底书", "好的，这是初稿…", llm_config=_cfg(),
        )
    # get_llm 被调用，且传的是 ResolvedLLMConfig（不是 kwargs）
    m_get.assert_called_once()
    arg = m_get.call_args.args[0]
    assert isinstance(arg, ResolvedLLMConfig)
    assert title == "专利交底书撰写"


def test_title_fallback_when_no_config(db_session):
    """llm_config=None → 不调 LLM，直接 fallback。"""
    conv = MagicMock()
    with patch("app.services.conversation_service.get_llm") as m_get:
        title = summarize_conversation_title(
            db_session, conv, "这是一个很长的用户消息超过二十个字的情况", "ai 回复", llm_config=None,
        )
    m_get.assert_not_called()
    assert title.startswith("这是一个很长的用户消息")
    assert title.endswith("...")


def test_title_fallback_on_llm_error(db_session):
    """LLM 调用抛异常 → fallback（不崩）。"""
    conv = MagicMock()
    with patch("app.services.conversation_service.get_llm") as m_get:
        m_get.return_value.invoke.side_effect = Exception("boom")
        title = summarize_conversation_title(
            db_session, conv, "短消息", "ai 回复", llm_config=_cfg(),
        )
    assert title == "短消息"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd apps/api && uv run pytest tests/test_conversation_title.py -v`
Expected: FAIL — `test_title_calls_llm_when_config_provided` 会失败（因为原代码 `get_llm(**{...})` 的实现现在指向模块内 import 的 get_llm，但参数不匹配；且 mock 路径 `app.services.conversation_service.get_llm` 当前不存在因为 get_llm 是函数内 import）。需先看失败细节。

> 注：原代码 `get_llm` 是在函数体内 `from app.ai.llm_client import get_llm` 局部 import。要 mock 必须把它提到模块级 import。Step 3 会做这件事。

- [ ] **Step 3: 修复 conversation_service.py**

Modify `apps/api/app/services/conversation_service.py` — replace the entire file content (52 lines) with:

```python
"""会话服务：标题总结等会话相关业务逻辑。"""

from sqlalchemy.orm import Session

from app.ai.llm_client import get_llm
from app.models import Conversation
from app.services.llm_config_service import ResolvedLLMConfig


def summarize_conversation_title(
    db: Session,
    conversation: Conversation,
    first_user_msg: str,
    first_ai_msg: str,
    llm_config: ResolvedLLMConfig | None = None,
) -> str:
    """用 LLM 根据首条对话内容生成简短标题。失败降级为用户消息前 20 字。

    llm_config 由调用方从 llm_config_service.resolve_llm_config 解析后传入。
    无配置（None）时直接降级，不调 LLM。

    F1 修复：原代码 get_llm(**{base_url,api_key,model}) 传错参数（get_llm 期望
    ResolvedLLMConfig 位置参数），TypeError 被 except Exception 吞掉，标题摘要
    始终静默 fallback。改为直接传 llm_config。
    """
    fallback = first_user_msg[:20] + ("..." if len(first_user_msg) > 20 else "")
    if llm_config is None:
        return fallback
    try:
        from langchain_core.messages import HumanMessage

        llm = get_llm(llm_config)
        resp = llm.invoke(
            [
                HumanMessage(
                    content=(
                        "请根据以下对话生成一个简短的中文标题"
                        "（不超过 12 个字，不要引号、不要句号、不要「标题：」前缀）：\n\n"
                        f"用户：{first_user_msg[:500]}\nAI：{first_ai_msg[:500]}\n\n标题："
                    )
                )
            ]
        )
        title = resp.content.strip().strip('""""\'').strip("。.").strip()[:50]
        return title or fallback
    except Exception:
        return fallback
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd apps/api && uv run pytest tests/test_conversation_title.py -v`
Expected: PASS（3 测试全绿）。

- [ ] **Step 5: 跑全量后端测试回归**

Run: `cd apps/api && uv run pytest -x`
Expected: PASS（确认没破坏现有功能。`summarize_conversation_title` 的调用方——若有测试覆盖——应仍通过；get_llm 签名未变）。

- [ ] **Step 6: 提交**

```bash
cd apps/api && git add app/services/conversation_service.py tests/test_conversation_title.py
git commit -m "fix(conversation): 修复标题摘要 get_llm 调用——传 ResolvedLLMConfig 而非 kwargs（F1）"
```

---

## Task 8: 后端全量回归 + 收尾

- [ ] **Step 1: 跑全部后端测试**

Run: `cd apps/api && uv run pytest -v`
Expected: 全绿。若有失败，逐一排查（不跳过、不 xfail）。

- [ ] **Step 2: 启动后端冒烟**

Run: `cd apps/api && uv run uvicorn app.main:app --reload &`，然后 curl 验证新端点存在：
```bash
curl -s http://localhost:8000/api/v1/settings/llm/templates  # 应返回 401（未登录），不是 404
```
Expected: `{"detail":"未登录"}` 或类似 401，**不是 404**。验证后停掉 uvicorn。

- [ ] **Step 3: 提交（如无改动则跳过）**

后端部分完成。继续前端。

---

## Task 9: 前端类型 + API client + React Query hooks

**Files:**
- Modify: `apps/web/src/types/api.ts`
- Modify: `apps/web/src/lib/api.ts`
- Modify: `apps/web/src/lib/queries.ts`

- [ ] **Step 1: 加类型**

Modify `apps/web/src/types/api.ts` — append at end of file:

```ts
// ── LLM provider 模板（添加配置时选模板自动填）──
export interface ProviderTemplate {
  id: string
  name: string
  base_url: string
  default_model: string
  default_embedding_model: string | null
  models_endpoint: string
  docs_url: string | null
  note: string | null
}

// ── 测试连接结果（chat + embedding 双测）──
export interface TestConnectionResult {
  ok: boolean
  chat: {
    ok: boolean
    latency_ms: number | null
    sample: string | null
    error: string | null
  }
  embedding: {
    ok: boolean
    latency_ms: number | null
    dim: number | null
    error: string | null
  } | null
  error: string | null
}

// ── 拉取模型列表结果 ──
export interface ListModelsResult {
  models: string[]
  truncated: boolean
  error: string | null
}
```

- [ ] **Step 2: 加 API client 函数**

Modify `apps/web/src/lib/api.ts` — 找到现有 `testMyLLM`（约 L394-405 区域），在其附近追加/改造。先读确认现有 `testMyLLM` 签名：

```ts
// 改造现有 testMyLLM（返回类型变 TestConnectionResult）
export const testMyLLM = (b: { base_url: string; api_key: string; model: string; embedding_model?: string | null }) =>
  api.post<TestConnectionResult>('/settings/llm/test', b)

// 新增
export const listProviderTemplates = () =>
  api.get<ProviderTemplate[]>('/settings/llm/templates')

export const listProviderModels = (b: { base_url: string; api_key: string; provider_template_id?: string | null }) =>
  api.post<ListModelsResult>('/settings/llm/models', b)

// admin 新增
export const testGlobalLLM = (b: { base_url?: string; api_key?: string; model?: string; embedding_model?: string | null }) =>
  api.post<TestConnectionResult>('/admin/llm-config/test', b)

export const listGlobalProviderModels = (b: { base_url: string; api_key: string; provider_template_id?: string | null }) =>
  api.post<ListModelsResult>('/admin/llm-config/models', b)
```

> 注：`api.post` / `api.get` 的封装风格需与现有代码一致——先读 `lib/api.ts` 顶部确认 `api` 对象的 `get`/`post` 方法签名（是否需要显式泛型、是否自动加 `/api/v1` 前缀）。保持一致。import `ProviderTemplate`/`TestConnectionResult`/`ListModelsResult` from `types/api`。

- [ ] **Step 3: 加 React Query hooks**

Modify `apps/web/src/lib/queries.ts` — append:

```ts
// ── LLM provider 模板 / 模型拉取 / 测试连接 ──
export function useProviderTemplates() {
  return useQuery({
    queryKey: ['llm-templates'],
    queryFn: api.listProviderTemplates,
    staleTime: Infinity,  // 静态数据，不主动刷新
  })
}

// 模型拉取与测试是命令式动作（按需触发），用 mutation
export function useListProviderModels() {
  return useMutation({
    mutationFn: (b: { base_url: string; api_key: string; provider_template_id?: string | null }) =>
      api.listProviderModels(b),
  })
}

export function useTestLLMConnection() {
  return useMutation({
    mutationFn: (b: { base_url: string; api_key: string; model: string; embedding_model?: string | null }) =>
      api.testMyLLM(b),
  })
}

export function useTestGlobalLLM() {
  return useMutation({
    mutationFn: (b: { base_url?: string; api_key?: string; model?: string; embedding_model?: string | null }) =>
      api.testGlobalLLM(b),
  })
}

export function useListGlobalProviderModels() {
  return useMutation({
    mutationFn: (b: { base_url: string; api_key: string; provider_template_id?: string | null }) =>
      api.listGlobalProviderModels(b),
  })
}
```

(确认 `queries.ts` 顶部已 import `useQuery`/`useMutation`/`api`——应已有，沿用现有 import 风格。)

- [ ] **Step 4: 类型检查 + 构建**

Run: `cd apps/web && pnpm build`
Expected: 构建成功（新类型/函数被定义但未消费，TS 不会报未使用错误如果是 `export`）。若有 lint 报错，修。

- [ ] **Step 5: 提交**

```bash
cd apps/web && git add src/types/api.ts src/lib/api.ts src/lib/queries.ts
git commit -m "feat(web): LLM 模板/测试/拉模型的 API client + 类型 + React Query hooks"
```

---

## Task 10: `llm-source.ts` 加全局默认便捷函数

**Files:**
- Modify: `apps/web/src/lib/llm-source.ts`

- [ ] **Step 1: 追加便捷函数**

Modify `apps/web/src/lib/llm-source.ts` — append at end of file:

```ts
/** 当前默认是否为全局 Key。 */
export function isGlobalDefault(): boolean {
  return getDefaultSource() === 'global'
}

/** 设/取消「全局 Key 作为默认」。set(true) → source='global'；set(false) 且当前是 global → 清空。 */
export function setGlobalDefault(value: boolean): void {
  if (value) {
    setDefaultSource('global')
  } else if (isGlobalDefault()) {
    clearDefaultSource()
  }
}
```

- [ ] **Step 2: 类型检查**

Run: `cd apps/web && pnpm build`
Expected: 成功。

- [ ] **Step 3: 提交**

```bash
cd apps/web && git add src/lib/llm-source.ts
git commit -m "feat(web): llm-source 加 isGlobalDefault/setGlobalDefault 便捷函数"
```

---

## Task 11: 手写 Switch 组件

**Files:**
- Create: `apps/web/src/components/ui/switch.tsx`

> 背景：shadcn CLI 与 MCP SDK 冲突装不了组件（GOTCHAS F8），要新组件手写。Switch 用于 admin 全局配置的 enabled 开关（替换原生 checkbox）。

- [ ] **Step 1: 读现有 Input/Button 组件风格**

Read `apps/web/src/components/ui/button.tsx` 和 `apps/web/src/components/ui/input.tsx`，理解项目的 className 约定（CSS 变量、size、variant 模式）。

- [ ] **Step 2: 实现 Switch**

Create `apps/web/src/components/ui/switch.tsx`:

```tsx
'use client'

import * as React from 'react'
import { cn } from '@/lib/utils'

export interface SwitchProps {
  checked: boolean
  onCheckedChange: (checked: boolean) => void
  disabled?: boolean
  className?: string
  'aria-label'?: string
}

/**
 * 手写 Switch（shadcn CLI 装不了，GOTCHAS F8）。
 * Apple Liquid Glass 风格：pill track + 滑块；关闭灰、开启用 primary（墨黑）。
 * 触摸区 ≥44px（外层 padding 撑开）。
 */
export const Switch = React.forwardRef<HTMLButtonElement, SwitchProps>(
  ({ checked, onCheckedChange, disabled, className, ...rest }, ref) => {
    return (
      <button
        ref={ref}
        type="button"
        role="switch"
        aria-checked={checked}
        disabled={disabled}
        onClick={() => onCheckedChange(!checked)}
        className={cn(
          'relative inline-flex h-[26px] w-[44px] shrink-0 cursor-pointer items-center rounded-full transition-colors',
          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2',
          'disabled:cursor-not-allowed disabled:opacity-50',
          checked ? 'bg-primary' : 'bg-muted',
          className,
        )}
        style={{ padding: '2px' }}
        {...rest}
      >
        <span
          className={cn(
            'pointer-events-none block size-[22px] rounded-full bg-white shadow-sm transition-transform',
            checked ? 'translate-x-[18px]' : 'translate-x-0',
          )}
        />
      </button>
    )
  },
)
Switch.displayName = 'Switch'
```

> 注：`bg-primary`/`bg-muted`/`ring-primary` 是项目 globals.css 已定义的 CSS 变量类（天工用墨黑 primary）。若项目命名不同（如 `bg-ink`），按 `button.tsx` 的实际用法对齐。

- [ ] **Step 3: 类型检查**

Run: `cd apps/web && pnpm build`
Expected: 成功（组件未被使用，但 export 合法）。

- [ ] **Step 4: 提交**

```bash
cd apps/web && git add src/components/ui/switch.tsx
git commit -m "feat(web): 手写 Switch 组件（pill 式开关，GOTCHAS F8）"
```

---

## Task 12: `TestResultBadge` 组件

**Files:**
- Create: `apps/web/src/components/llm-config/TestResultBadge.tsx`

- [ ] **Step 1: 实现**

Create `apps/web/src/components/llm-config/TestResultBadge.tsx`:

```tsx
'use client'

import { cn } from '@/lib/utils'
import type { TestConnectionResult } from '@/types/api'

/**
 * 测试连接结果展示（Apple Liquid Glass：灰阶为主，状态点用单色 accent）。
 * 四态：成功（live 绿点）/ 警告（橙）/ 失败（红）/ 未测（灰）。
 * 分别展示 chat 与 embedding 两路结果。
 */
export function TestResultBadge({ result }: { result: TestConnectionResult | null }) {
  if (!result) return null

  return (
    <div className="space-y-1.5 rounded-lg border border-black/[0.07] bg-muted/30 p-3 text-[12px] dark:border-white/10">
      {/* chat */}
      <ResultLine label="对话模型" r={result.chat} />
      {/* embedding */}
      {result.embedding ? (
        <ResultLine label="嵌入模型" r={result.embedding} suffix={result.embedding.dim ? `${result.embedding.dim}维` : undefined} />
      ) : null}
      {/* 顶层错误兜底 */}
      {!result.ok && result.error && !result.chat.error && !result.embedding?.error && (
        <p className="text-destructive">{result.error}</p>
      )}
    </div>
  )
}

function ResultLine({
  label, r, suffix,
}: {
  label: string
  r: { ok: boolean; latency_ms: number | null; sample?: string | null; dim?: number | null; error: string | null }
  suffix?: string
}) {
  const dot = r.ok ? 'bg-[#30d158]' : 'bg-[#ff3b30]'
  const text = r.ok
    ? `已连通${r.latency_ms != null ? ` · ${r.latency_ms}ms` : ''}${suffix ? ` · ${suffix}` : ''}${r.sample ? ` · ${r.sample.slice(0, 30)}` : ''}`
    : r.error || '失败'
  return (
    <div className="flex items-center gap-2">
      <span className={cn('size-[7px] shrink-0 rounded-full', dot)} />
      <span className="font-medium text-foreground/70">{label}</span>
      <span className={cn(r.ok ? 'text-muted-foreground' : 'text-destructive')}>{text}</span>
    </div>
  )
}
```

- [ ] **Step 2: 类型检查**

Run: `cd apps/web && pnpm build`
Expected: 成功。

- [ ] **Step 3: 提交**

```bash
cd apps/web && git add src/components/llm-config/TestResultBadge.tsx
git commit -m "feat(web): TestResultBadge 组件——测试连接四态展示"
```

---

## Task 13: `ModelSelectInput` 组件

**Files:**
- Create: `apps/web/src/components/llm-config/ModelSelectInput.tsx`

- [ ] **Step 1: 实现**

Create `apps/web/src/components/llm-config/ModelSelectInput.tsx`:

```tsx
'use client'

import { useState } from 'react'
import { ChevronDown } from 'lucide-react'
import { cn } from '@/lib/utils'

/**
 * 模型选择输入：下拉（来自拉取结果）+ 可手输（自由文本）。
 * 决策 D5：每个 config 仍只存一个 model 字符串；拉取结果只作建议项，不落库。
 *
 * - 下拉有数据时：点 ▾ 展开，选中填入；也可直接在输入框打字覆盖。
 * - 下拉空时：纯输入框。
 */
export interface ModelSelectInputProps {
  value: string
  onChange: (v: string) => void
  options: string[]               // 来自拉取结果
  placeholder?: string
  loading?: boolean               // 拉取中
  error?: string | null           // 拉取失败提示
  className?: string
}

export function ModelSelectInput({
  value, onChange, options, placeholder = '输入或选择模型名', loading, error, className,
}: ModelSelectInputProps) {
  const [open, setOpen] = useState(false)

  return (
    <div className={cn('relative', className)}>
      <div className="flex items-center gap-1.5">
        <input
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          className="h-9 flex-1 rounded-lg border border-black/[0.1] bg-background px-3 text-[13px] outline-none focus:border-primary dark:border-white/15"
        />
        {options.length > 0 && (
          <button
            type="button"
            onClick={() => setOpen((o) => !o)}
            className="flex size-9 shrink-0 items-center justify-center rounded-lg border border-black/[0.1] text-muted-foreground hover:bg-muted dark:border-white/15"
            aria-label="展开模型列表"
          >
            <ChevronDown className={cn('size-4 transition-transform', open && 'rotate-180')} />
          </button>
        )}
      </div>

      {loading && <p className="mt-1 text-[11px] text-muted-foreground">拉取中…</p>}
      {error && <p className="mt-1 text-[11px] text-destructive">{error}</p>}

      {open && options.length > 0 && (
        <div className="absolute z-20 mt-1 max-h-52 w-full overflow-auto rounded-lg border border-black/[0.07] bg-popover p-1 shadow-md dark:border-white/10">
          {options.map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => { onChange(m); setOpen(false) }}
              className={cn(
                'block w-full rounded px-2.5 py-1.5 text-left font-mono text-[12px] hover:bg-muted',
                m === value && 'bg-muted font-medium',
              )}
            >
              {m}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
```

> 注：`bg-background`/`bg-popover`/`border-primary`/`text-muted-foreground` 需与项目 globals.css 的 token 类一致。先读 `input.tsx` 确认命名。

- [ ] **Step 2: 类型检查**

Run: `cd apps/web && pnpm build`
Expected: 成功。

- [ ] **Step 3: 提交**

```bash
cd apps/web && git add src/components/llm-config/ModelSelectInput.tsx
git commit -m "feat(web): ModelSelectInput——下拉+手输模型选择"
```

---

## Task 14: `ProviderTemplatePicker` 组件

**Files:**
- Create: `apps/web/src/components/llm-config/ProviderTemplatePicker.tsx`

- [ ] **Step 1: 实现**

Create `apps/web/src/components/llm-config/ProviderTemplatePicker.tsx`:

```tsx
'use client'

import { ExternalLink } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { ProviderTemplate } from '@/types/api'

/**
 * provider 模板 chip 条（横向滚动）。点选后回调填充 base_url/默认模型。
 * Apple 风格：灰阶 chip，选中用 accent（蓝色文字 + 淡蓝底）。
 */
export interface ProviderTemplatePickerProps {
  templates: ProviderTemplate[]
  selectedId: string | null
  onSelect: (t: ProviderTemplate) => void
}

export function ProviderTemplatePicker({ templates, selectedId, onSelect }: ProviderTemplatePickerProps) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {templates.map((t) => {
        const active = t.id === selectedId
        return (
          <button
            key={t.id}
            type="button"
            onClick={() => onSelect(t)}
            title={t.note || undefined}
            className={cn(
              'inline-flex items-center gap-1 rounded-full px-3 py-1.5 text-[12px] font-medium transition-colors',
              active
                ? 'bg-[rgba(0,113,227,0.08)] text-[#0071e3]'
                : 'bg-muted text-muted-foreground hover:bg-muted/70',
            )}
          >
            {t.name}
            {t.docs_url && active && (
              <a
                href={t.docs_url}
                target="_blank"
                rel="noreferrer"
                onClick={(e) => e.stopPropagation()}
                className="ml-0.5 inline-flex"
                aria-label="如何获取 API Key"
              >
                <ExternalLink className="size-3" />
              </a>
            )}
          </button>
        )
      })}
    </div>
  )
}
```

- [ ] **Step 2: 类型检查 + 提交**

Run: `cd apps/web && pnpm build`，Expected: 成功。

```bash
cd apps/web && git add src/components/llm-config/ProviderTemplatePicker.tsx
git commit -m "feat(web): ProviderTemplatePicker——模板 chip 条"
```

---

## Task 15: `LLMConfigEditPanel` 组件（核心）

**Files:**
- Create: `apps/web/src/components/llm-config/LLMConfigEditPanel.tsx`

> 这是最大的组件。包含：模板 picker、名称、base_url、api_key（眼睛）、对话模型（ModelSelectInput+拉取）、embedding 模型（同）、测试按钮+TestResultBadge、保存/取消。admin 与用户共用，通过 props 区分（admin 多 allowed_models）。

- [ ] **Step 1: 实现**

Create `apps/web/src/components/llm-config/LLMConfigEditPanel.tsx`:

```tsx
'use client'

import { useState } from 'react'
import { Eye, EyeOff } from 'lucide-react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input
import { Label } from '@/components/ui/label'
import { ModelSelectInput } from './ModelSelectInput'
import { ProviderTemplatePicker } from './ProviderTemplatePicker'
import { TestResultBadge } from './TestResultBadge'
import { cn } from '@/lib/utils'
import {
  useListProviderModels, useProviderTemplates, useTestLLMConnection,
} from '@/lib/queries'
import { api } from '@/lib/api'
import type { ProviderTemplate, TestConnectionResult } from '@/types/api'

export interface LLMConfigEditPanelProps {
  /** 初始值（编辑模式传入；新增模式传 null/undefined）。 */
  initial?: {
    name?: string
    base_url?: string
    api_key_masked?: string
    model?: string
    embedding_model?: string | null
    provider_template_id?: string | null
  } | null
  /** 保存回调。返回 Promise。apiKey 留空串 = 不改。 */
  onSave: (data: {
    name: string
    base_url: string
    api_key: string            // 留空 = 不改（由调用方判断）
    model: string
    embedding_model: string | null
    provider_template_id?: string | null
  }) => Promise<void>
  onCancel: () => void
  /** admin 模式：额外传 allowed_models 字段（编辑框）。 */
  adminMode?: boolean
  initialAllowedModels?: string[]
  /** admin 的 api_key 留空语义：编辑时留空=不改（同用户模式）。 */
  saveLabel?: string
}

export function LLMConfigEditPanel({
  initial, onSave, onCancel, adminMode, initialAllowedModels, saveLabel = '保存',
}: LLMConfigEditPanelProps) {
  const [name, setName] = useState(initial?.name ?? '')
  const [baseUrl, setBaseUrl] = useState(initial?.base_url ?? '')
  const [apiKey, setApiKey] = useState('')   // 始终空起步；留空=不改（编辑）或必填（新增由调用方校验）
  const [model, setModel] = useState(initial?.model ?? '')
  const [embeddingModel, setEmbeddingModel] = useState(initial?.embedding_model ?? '')
  const [selectedTplId, setSelectedTplId] = useState<string | null>(initial?.provider_template_id ?? null)
  const [showKey, setShowKey] = useState(false)
  const [allowedModelsStr, setAllowedModelsStr] = useState(
    (initialAllowedModels ?? []).join(', '),
  )

  // 拉取的模型列表（本地 state，不持久化）
  const [chatModels, setChatModels] = useState<string[]>([])
  const [embedModels, setEmbedModels] = useState<string[]>([])

  const [testResult, setTestResult] = useState<TestConnectionResult | null>(null)
  const [saving, setSaving] = useState(false)

  const listModels = useListProviderModels()
  const testConn = useTestLLMConnection()

  function pickTemplate(t: ProviderTemplate) {
    setSelectedTplId(t.id)
    // 自动填（仅在字段为空时填，避免覆盖用户已输入）
    if (!baseUrl) setBaseUrl(t.base_url)
    if (!model) setModel(t.default_model)
    if (!embeddingModel && t.default_embedding_model) setEmbeddingModel(t.default_embedding_model)
  }

  async function handleFetchModels(target: 'chat' | 'embed') {
    if (!baseUrl || !apiKey) {
      toast.error('请先填写 Base URL 和 API Key')
      return
    }
    const res = await listModels.mutateAsync({
      base_url: baseUrl, api_key: apiKey, provider_template_id: selectedTplId,
    })
    if (res.error) {
      toast.error(`拉取失败：${res.error}`)
      return
    }
    if (target === 'chat') setChatModels(res.models)
    else setEmbedModels(res.models)
    toast.success(`已拉取 ${res.models.length} 个模型${res.truncated ? '（已截断前 100）' : ''}`)
  }

  async function handleTest() {
    if (!baseUrl || !model) {
      toast.error('请先填写 Base URL 和 对话模型')
      return
    }
    // 新增模式下 apiKey 必填；编辑模式下若留空则用掩码提示（无法测已存值——用户侧无明文）
    if (!apiKey && !initial?.api_key_masked) {
      toast.error('请填写 API Key')
      return
    }
    if (!apiKey && initial?.api_key_masked) {
      toast.error('编辑模式下测试需重新填写 API Key（已存 Key 不回显明文）')
      return
    }
    const res = await testConn.mutateAsync({
      base_url: baseUrl, api_key: apiKey, model,
      embedding_model: embeddingModel || null,
    })
    setTestResult(res)
  }

  async function handleSave() {
    if (!name.trim() || !baseUrl.trim() || !model.trim()) {
      toast.error('名称、Base URL、对话模型不能为空')
      return
    }
    // 新增模式 apiKey 必填
    if (!initial && !apiKey) {
      toast.error('请填写 API Key')
      return
    }
    setSaving(true)
    try {
      await onSave({
        name: name.trim(),
        base_url: baseUrl.trim(),
        api_key: apiKey,   // 留空=不改（编辑）或已校验非空（新增）
        model: model.trim(),
        embedding_model: embeddingModel.trim() || null,
        provider_template_id: selectedTplId,
        ...(adminMode ? { allowed_models: allowedModelsStr } : {}),
      } as any)
    } catch (e: any) {
      toast.error(`保存失败：${e?.message || e}`)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-4 bg-muted/20 p-5">
      {/* 模板 */}
      <div className="space-y-2">
        <Label className="text-[12px] text-muted-foreground">从模板开始（可选）</Label>
        <TemplateSection selectedId={selectedTplId} onPick={pickTemplate} />
      </div>

      {/* 名称 + base_url */}
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <div className="space-y-1.5">
          <Label className="text-[12px]">名称</Label>
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="如：公司主 Key" />
        </div>
        <div className="space-y-1.5">
          <Label className="text-[12px]">API Base URL</Label>
          <Input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://..." />
        </div>
      </div>

      {/* api_key */}
      <div className="space-y-1.5">
        <Label className="text-[12px]">
          API Key
          {initial?.api_key_masked && (
            <span className="ml-2 text-[11px] text-muted-foreground">
              当前：{initial.api_key_masked}（留空不修改）
            </span>
          )}
        </Label>
        <div className="relative">
          <Input
            type={showKey ? 'text' : 'password'}
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder={initial?.api_key_masked ? '输入新 Key（留空不改）' : '输入 API Key'}
            className="pr-10 font-mono"
          />
          <button
            type="button"
            onClick={() => setShowKey((s) => !s)}
            className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
            aria-label={showKey ? '隐藏' : '显示'}
          >
            {showKey ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
          </button>
        </div>
      </div>

      {/* 对话模型 + 拉取 */}
      <div className="space-y-1.5">
        <div className="flex items-center justify-between">
          <Label className="text-[12px]">对话模型</Label>
          <Button
            type="button" size="xs" variant="outline"
            disabled={listModels.isPending}
            onClick={() => handleFetchModels('chat')}
          >
            {listModels.isPending ? '拉取中…' : '⤓ 拉取模型'}
          </Button>
        </div>
        <ModelSelectInput
          value={model}
          onChange={setModel}
          options={chatModels}
          placeholder="如 glm-4-plus"
        />
      </div>

      {/* embedding 模型 + 拉取 */}
      <div className="space-y-1.5">
        <div className="flex items-center justify-between">
          <Label className="text-[12px]">嵌入模型（可选，知识库 RAG 用）</Label>
          <Button
            type="button" size="xs" variant="outline"
            disabled={listModels.isPending}
            onClick={() => handleFetchModels('embed')}
          >
            ⤓ 拉取
          </Button>
        </div>
        <ModelSelectInput
          value={embeddingModel}
          onChange={setEmbeddingModel}
          options={embedModels}
          placeholder="如 embedding-3（留空则不测）"
        />
      </div>

      {/* admin: allowed_models */}
      {adminMode && (
        <div className="space-y-1.5">
          <Label className="text-[12px]">允许的模型（逗号分隔，留空不限制）</Label>
          <Input
            value={allowedModelsStr}
            onChange={(e) => setAllowedModelsStr(e.target.value)}
            placeholder="glm-4-plus, glm-4-flash"
          />
          <p className="text-[11px] text-muted-foreground">保存时按英文逗号拆分为列表。</p>
        </div>
      )}

      {/* 测试结果 */}
      {testResult && <TestResultBadge result={testResult} />}

      {/* 操作 */}
      <div className="flex items-center justify-between border-t border-black/[0.07] pt-4 dark:border-white/10">
        <Button
          type="button" variant="outline" size="sm"
          disabled={testConn.isPending}
          onClick={handleTest}
        >
          {testConn.isPending ? '测试中…' : '↻ 测试连接'}
        </Button>
        <div className="flex gap-2">
          <Button type="button" variant="ghost" size="sm" onClick={onCancel}>取消</Button>
          <Button type="button" size="sm" disabled={saving} onClick={handleSave}>
            {saving ? '保存中…' : saveLabel}
          </Button>
        </div>
      </div>
    </div>
  )
}

// 模板区子组件（隔离 React Query 的加载态）
function TemplateSection({
  selectedId, onPick,
}: {
  selectedId: string | null
  onPick: (t: ProviderTemplate) => void
}) {
  const { data: templates, isLoading } = useProviderTemplates()
  if (isLoading || !templates) return <p className="text-[11px] text-muted-foreground">加载模板…</p>
  return <ProviderTemplatePicker templates={templates} selectedId={selectedId} onSelect={onPick} />
}
```

> 设计说明：`useProviderTemplates` 通过子组件 `TemplateSection` 调用，避免主组件因模板加载态重渲染影响表单输入。模板数据 `staleTime: Infinity`（静态），加载一次后缓存。

- [ ] **Step 2: 类型检查 + 构建**

Run: `cd apps/web && pnpm build`
Expected: 成功。修任何 TS 报错。

- [ ] **Step 3: 提交**

```bash
cd apps/web && git add src/components/llm-config/LLMConfigEditPanel.tsx
git commit -m "feat(web): LLMConfigEditPanel——内联展开编辑面板（模板/测试/拉模型/admin allowed_models）"
```

---

## Task 16: `LLMConfigRow` 组件

**Files:**
- Create: `apps/web/src/components/llm-config/LLMConfigRow.tsx`

- [ ] **Step 1: 实现**

Create `apps/web/src/components/llm-config/LLMConfigRow.tsx`:

```tsx
'use client'

import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import type { UserLLMConfig } from '@/types/api'

/**
 * 配置列表中的一行（unified panel 内的一行，带 hairline）。
 * 默认态：accent 圆点 + 蓝色「默认」徽章；非默认：右侧「设为默认」ghost 按钮。
 */
export interface LLMConfigRowProps {
  config: UserLLMConfig
  isDefault: boolean
  onSetDefault: () => void
  onEdit: () => void
  onDelete: () => void
  /** 该行是否处于编辑展开态（展开时不显示操作按钮，由面板接管）。 */
  isEditing?: boolean
}

export function LLMConfigRow({
  config, isDefault, onSetDefault, onEdit, onDelete, isEditing,
}: LLMConfigRowProps) {
  return (
    <div
      className={cn(
        'flex items-center justify-between gap-3 px-5 py-4 transition-colors',
        'border-t border-black/[0.07] first:border-t-0 dark:border-white/10',
        isEditing && 'bg-transparent',
      )}
    >
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          {isDefault && <span className="size-[7px] shrink-0 rounded-full bg-[#0071e3]" />}
          <span className="truncate text-[14px] font-semibold">{config.name}</span>
          {isDefault && (
            <span className="shrink-0 rounded-full bg-[rgba(0,113,227,0.08)] px-2 py-0.5 text-[11px] font-semibold text-[#0071e3]">
              默认
            </span>
          )}
        </div>
        <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[12px] text-muted-foreground">
          <span className="font-mono">{config.model}</span>
          <span>·</span>
          <span className="font-mono">{config.api_key_masked}</span>
          {config.embedding_model && (
            <>
              <span>·</span>
              <span>embed: {config.embedding_model}</span>
            </>
          )}
        </div>
      </div>

      {!isEditing && (
        <div className="flex shrink-0 gap-1.5">
          {!isDefault && (
            <Button size="xs" variant="outline" onClick={onSetDefault}>设为默认</Button>
          )}
          <Button size="xs" variant="outline" onClick={onEdit}>编辑</Button>
          <Button size="xs" variant="ghost" className="text-destructive hover:text-destructive" onClick={onDelete}>
            删除
          </Button>
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 2: 类型检查 + 提交**

Run: `cd apps/web && pnpm build`，Expected: 成功。

```bash
cd apps/web && git add src/components/llm-config/LLMConfigRow.tsx
git commit -m "feat(web): LLMConfigRow——配置行（accent 圆点默认态 + 操作按钮）"
```

---

## Task 17: 重构用户页 `/settings`

**Files:**
- Modify: `apps/web/src/app/(app)/settings/page.tsx`

> 改动：去掉 `SourceSelector`（顶部 radio）；改用 `LLMConfigRow` + `LLMConfigEditPanel` 内联展开；加全局 Key toggle（授权态显示）；删除加确认。

- [ ] **Step 1: 读现有完整文件**

Read `apps/web/src/app/(app)/settings/page.tsx` 全文（约 530 行），理解 `PageShell`/`PageHeader`/`CreateDialog`/`EditDialog`/`SourceSelector`/`SourceOption`/`ConfigList` 各部分，以及默认 source 的 useEffect 校验逻辑（约 L42-79）。

- [ ] **Step 2: 重写 page.tsx**

Replace the entire file. 结构：

```tsx
'use client'

import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import { PageShell, PageHeader } from '@/components/page-shell'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { LLMConfigRow } from '@/components/llm-config/LLMConfigRow'
import { LLMConfigEditPanel } from '@/components/llm-config/LLMConfigEditPanel'
import { api } from '@/lib/api'
import {
  getDefaultSource, setDefaultSource, clearDefaultSource,
  isGlobalDefault, setGlobalDefault,
} from '@/lib/llm-source'
import type { UserLLMConfig } from '@/types/api'

export default function SettingsPage() {
  const qc = useQueryClient()
  const [editingId, setEditingId] = useState<string | null>(null)  // null=无；'new'=新增；uuid=编辑某条
  const [deleting, setDeleting] = useState<UserLLMConfig | null>(null)

  const configsQuery = useQuery({ queryKey: ['my-llm'], queryFn: api.listMyLLM })
  const grantQuery = useQuery({ queryKey: ['my-grant'], queryFn: api.getMyGrant })

  const configs = configsQuery.data ?? []
  const grantActive = !!grantQuery.data?.is_active
  const currentDefault = getDefaultSource()

  const invalidate = () => qc.invalidateQueries({ queryKey: ['my-llm'] })

  const createMut = useMutation({
    mutationFn: (d: any) => api.createMyLLM(d),
    onSuccess: () => { invalidate(); toast.success('配置已添加'); setEditingId(null) },
  })
  const updateMut = useMutation({
    mutationFn: ({ id, d }: { id: string; d: any }) => api.updateMyLLM(id, d),
    onSuccess: () => { invalidate(); toast.success('配置已更新'); setEditingId(null) },
  })
  const deleteMut = useMutation({
    mutationFn: (id: string) => api.deleteMyLLM(id),
    onSuccess: () => {
      invalidate(); toast.success('配置已删除')
      if (deleting && getDefaultSource() === `custom:${deleting.id}`) clearDefaultSource()
      setDeleting(null)
    },
  })

  return (
    <PageShell>
      <PageHeader title="LLM 配置" description="管理你的自定义 LLM 配置，选择默认使用的来源">
        <Button size="sm" onClick={() => setEditingId('new')}>+ 添加配置</Button>
      </PageHeader>

      <div className="py-6 space-y-6">
        {/* 全局 Key toggle（仅被授权时显示） */}
        {grantActive && (
          <div className="flex items-center justify-between rounded-2xl border border-black/[0.07] bg-card px-5 py-3.5 dark:border-white/10"
               style={{ boxShadow: 'var(--shadow-card)' }}>
            <div>
              <p className="text-[13px] font-medium">使用全局 Key 作为默认</p>
              <p className="text-[12px] text-muted-foreground">你已被授权使用管理员配置的全局 Key</p>
            </div>
            <Switch
              checked={isGlobalDefault()}
              onCheckedChange={(v) => {
                setGlobalDefault(v)
                qc.invalidateQueries({ queryKey: ['my-llm'] })  // 触发重渲染
              }}
            />
          </div>
        )}

        {/* 配置列表（unified panel） */}
        <div className="overflow-hidden rounded-2xl border border-black/[0.07] bg-card dark:border-white/10"
             style={{ boxShadow: 'var(--shadow-card)' }}>
          {configs.length === 0 && editingId !== 'new' && (
            <p className="px-5 py-10 text-center text-[13px] text-muted-foreground">
              暂无配置，点击右上角「+ 添加配置」开始
            </p>
          )}

          {configs.map((c) => (
            <div key={c.id}>
              <LLMConfigRow
                config={c}
                isDefault={currentDefault === `custom:${c.id}`}
                isEditing={editingId === c.id}
                onSetDefault={() => { setDefaultSource(`custom:${c.id}`); qc.invalidateQueries({ queryKey: ['my-llm'] }) }}
                onEdit={() => setEditingId(c.id)}
                onDelete={() => setDeleting(c)}
              />
              {editingId === c.id && (
                <LLMConfigEditPanel
                  initial={{
                    name: c.name, base_url: c.base_url, api_key_masked: c.api_key_masked,
                    model: c.model, embedding_model: c.embedding_model,
                  }}
                  onCancel={() => setEditingId(null)}
                  onSave={async (d) => {
                    await updateMut.mutateAsync({ id: c.id, d: {
                      name: d.name, base_url: d.base_url,
                      api_key: d.api_key || undefined,  // 留空不传=不改
                      model: d.model, embedding_model: d.embedding_model,
                    } })
                  }}
                />
              )}
            </div>
          ))}

          {/* 新增面板（追加在列表底部） */}
          {editingId === 'new' && (
            <LLMConfigEditPanel
              initial={null}
              onCancel={() => setEditingId(null)}
              onSave={async (d) => {
                await createMut.mutateAsync({
                  name: d.name, base_url: d.base_url, api_key: d.api_key,
                  model: d.model, embedding_model: d.embedding_model,
                })
              }}
            />
          )}
        </div>
      </div>

      {/* 删除确认（项目无通用 ConfirmDialog，用 Dialog 手写——与 delete-confirm-dialog.tsx 同构） */}
      {deleting && (
        <Dialog open onOpenChange={(o) => !o && setDeleting(null)}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>确认删除</DialogTitle>
              <DialogDescription>
                确认删除配置「{deleting.name}」？此操作不可恢复。若它是当前默认，删除后需重新选择默认来源。
              </DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <Button variant="outline" onClick={() => setDeleting(null)}>取消</Button>
              <Button
                variant="destructive"
                disabled={deleteMut.isPending}
                onClick={() => deleteMut.mutate(deleting.id)}
              >
                {deleteMut.isPending ? '删除中…' : '确认删除'}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}
    </PageShell>
  )
}
```

> 关键确认点：① 项目**无**通用 `ConfirmDialog`（现有 `delete-confirm-dialog.tsx` 是项目专用、绑死 `useDeleteProject`，不可复用），故用 `Dialog` 手写内联确认，与现有项目删除对话框同构。② `PageShell`/`PageHeader` 的 props 签名以现有 settings 页为准（保持 title/description/children 结构）。③ `createMyLLM`/`updateMyLLM` 的入参类型与 `api.ts` 现有定义对齐。

- [ ] **Step 3: 删除旧的内联子组件**

原 `settings/page.tsx` 里的 `SourceSelector`/`SourceOption`/`ConfigList`/`CreateDialog`/`EditDialog` 函数定义全部删除（已被新组件取代）。

- [ ] **Step 4: 类型检查 + 构建**

Run: `cd apps/web && pnpm build`
Expected: 成功。修任何 import/类型错误。

- [ ] **Step 5: 手动冒烟（可选，有 dev server 时）**

Run: `cd apps/web && pnpm dev`，访问 `http://localhost:3000/settings`：
- 配置列表显示为 unified panel 行
- 点「+ 添加配置」→ 列表底部展开面板，模板 chip 条可见
- 点「编辑」→ 该行下方展开面板
- 点「设为默认」→ 该行出现蓝点 + 默认徽章，其他行恢复
- 被授权时全局 Key toggle 显示

- [ ] **Step 6: 提交**

```bash
cd apps/web && git add 'src/app/(app)/settings/page.tsx'
git commit -m "feat(web): /settings 重构——去 radio、unified panel、内联展开、全局 toggle"
```

---

## Task 18: 重构 admin 页 `/admin/console/llm`

**Files:**
- Modify: `apps/web/src/app/(app)/admin/console/llm/page.tsx`

> 改动：enabled 原生 checkbox 换 Switch；接入 `LLMConfigEditPanel`（admin 模式）；加测试（保存前用表单值、保存后用「已存值复检」）；加拉模型。

- [ ] **Step 1: 读现有完整文件**

Read `apps/web/src/app/(app)/admin/console/llm/page.tsx` 全文，理解现有 `getGlobalLLM`/`setGlobalLLM` 调用、`initialized` 一次性 hydrate 模式、字段 state。

- [ ] **Step 2: 重写 page.tsx**

Replace the entire file. admin 页只有一个配置（全局），直接用一个常驻 `LLMConfigEditPanel`（不展开/收起，因为只有一个）：

```tsx
'use client'

import { useEffect, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import { PageShell, PageHeader } from '@/components/page-shell'
import { Switch } from '@/components/ui/switch'
import { Button } from '@/components/ui/button'
import { LLMConfigEditPanel } from '@/components/llm-config/LLMConfigEditPanel'
import { TestResultBadge } from '@/components/llm-config/TestResultBadge'
import { api } from '@/lib/api'
import { useTestGlobalLLM } from '@/lib/queries'
import type { GlobalLLMSettings, TestConnectionResult } from '@/types/api'

export default function AdminLLMPage() {
  const qc = useQueryClient()
  const [enabled, setEnabled] = useState(true)
  const [hydrated, setHydrated] = useState(false)
  const [recheckResult, setRecheckResult] = useState<TestConnectionResult | null>(null)

  const cfgQuery = useQuery({ queryKey: ['admin', 'llm-config'], queryFn: api.getGlobalLLM })
  const saveMut = useMutation({
    mutationFn: (d: any) => api.setGlobalLLM(d),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin', 'llm-config'] })
      qc.invalidateQueries({ queryKey: ['admin', 'audit-logs'] })
      toast.success('全局配置已保存')
    },
  })
  const testGlobal = useTestGlobalLLM()

  // 一次性 hydrate（避免覆盖编辑）
  useEffect(() => {
    if (!hydrated && cfgQuery.data) {
      setEnabled(cfgQuery.data.llm_global_enabled)
      setHydrated(true)
    }
  }, [hydrated, cfgQuery.data])

  const gc = cfgQuery.data?.global_config

  async function handleRecheck() {
    const res = await testGlobal.mutateAsync({})  // 空 body → 用已存值
    setRecheckResult(res)
  }

  return (
    <PageShell>
      <PageHeader title="全局 LLM 配置" description="管理员配置供全平台使用的 LLM（用户可申请授权使用）">
        <Button size="sm" variant="outline" onClick={handleRecheck} disabled={testGlobal.isPending}>
          {testGlobal.isPending ? '复检中…' : '↻ 用已存配置测试'}
        </Button>
      </PageHeader>

      <div className="py-6 space-y-5">
        {/* enabled 开关 */}
        <div className="flex items-center justify-between rounded-2xl border border-black/[0.07] bg-card px-5 py-3.5 dark:border-white/10"
             style={{ boxShadow: 'var(--shadow-card)' }}>
          <div>
            <p className="text-[13px] font-medium">提供全局 Key</p>
            <p className="text-[12px] text-muted-foreground">
              {enabled ? '开启：用户被授权后可使用此全局 Key' : '关闭：强制用户使用自己的自定义配置'}
            </p>
          </div>
          <Switch checked={enabled} onCheckedChange={setEnabled} />
        </div>

        {/* 复检结果 */}
        {recheckResult && <TestResultBadge result={recheckResult} />}

        {/* 编辑面板（admin 模式：常驻显示） */}
        <div className="overflow-hidden rounded-2xl border border-black/[0.07] bg-card dark:border-white/10"
             style={{ boxShadow: 'var(--shadow-card)' }}>
          <LLMConfigEditPanel
            initial={gc ? {
              name: '全局 Key',
              base_url: gc.base_url,
              api_key_masked: gc.api_key_masked,
              model: gc.model,
              embedding_model: gc.embedding_model,
            } : null}
            adminMode
            initialAllowedModels={gc?.allowed_models ?? []}
            saveLabel="保存全局配置"
            onCancel={() => toast.info('全局配置无需取消（常驻）')}
            onSave={async (d: any) => {
              await saveMut.mutateAsync({
                enabled,
                base_url: d.base_url,
                api_key: d.api_key || undefined,   // 留空=不改
                model: d.model,
                embedding_model: d.embedding_model,
                allowed_models: d.allowed_models
                  ? (d.allowed_models as string).split(',').map((s) => s.trim()).filter(Boolean)
                  : undefined,
              })
            }}
          />
        </div>
      </div>
    </PageShell>
  )
}
```

> 关键：admin 的 `LLMConfigEditPanel` 复用了用户版组件，但：① `adminMode` 开 `allowed_models` 编辑框；② 保存回调走 `setGlobalLLM`；③ 测试走「面板内测试」（用表单值，`useTestLLMConnection`）+ 顶部「用已存配置测试」（`useTestGlobalLLM` 空 body）两条路径。
>
> 注意：`LLMConfigEditPanel` 内的测试按钮（`handleTest`）调的是 `useTestLLMConnection`（走 `/settings/llm/test`，普通用户端点）。admin 也能调（端点鉴权是 `get_current_user`，admin 也是 user），功能等价。若要严格用 admin 端点，可在 EditPanel 加一个 `testFn` prop 注入——但 `/settings/llm/test` 逻辑与 admin 传入值测试完全一致，复用即可。

- [ ] **Step 3: 类型检查 + 构建**

Run: `cd apps/web && pnpm build`
Expected: 成功。

- [ ] **Step 4: 手动冒烟**

访问 `/admin/console/llm`：
- enabled Switch 可切换
- 模板 chip 条 + 字段 + 拉模型 + 测试全可用
- 「用已存配置测试」按钮调复检
- 保存写审计（查 `/admin/audit-logs`）

- [ ] **Step 5: 提交**

```bash
cd apps/web && git add 'src/app/(app)/admin/console/llm/page.tsx'
git commit -m "feat(web): /admin/console/llm 重构——Switch 开关、接入 EditPanel、测试+复检+拉模型"
```

---

## Task 19: 前端全量构建 + 手动 QA

- [ ] **Step 1: 全量构建**

Run: `cd apps/web && pnpm build`
Expected: 成功，无 TS/lint 错误。

- [ ] **Step 2: 启动前后端做手动 QA**

启动后端：`cd apps/api && uv run uvicorn app.main:app --reload`
启动前端：`cd apps/web && pnpm dev`

按 spec §九 的手动 QA 清单逐项验证：
- [ ] admin 与用户两页面视觉一致（unified panel + accent 圆点）
- [ ] 6 个模板逐个选 → base_url/模型自动填（仅填空字段，不覆盖）
- [ ] 智谱真 key 测 chat+embedding 全绿
- [ ] 故意填错 key 测 → 友好错误（API Key 无效）
- [ ] Ollama `/api/tags` 拉模型（需本地起 Ollama，否则验证错误提示）
- [ ] 内联展开/收起不丢其他行状态
- [ ] 设为默认互斥（含全局 toggle）
- [ ] 删除确认弹窗
- [ ] admin 保存后审计日志有记录

- [ ] **Step 3: 修复 QA 发现的问题，逐个提交**

- [ ] **Step 4: 最终全量测试**

后端：`cd apps/api && uv run pytest`
前端：`cd apps/web && pnpm build`
Expected: 全绿。

---

## Task 20: 更新 AGENTS.md / 文档（如需）

- [ ] **Step 1: 检查 AGENTS.md 是否需补充**

读 `AGENTS.md`，看是否需要在「关键约定」补一条关于 LLM 配置新功能的说明（如「provider 模板在 `app/services/llm_provider_templates.py`，新增供应商改这里」）。若有价值则加。

- [ ] **Step 2: 提交（如有改动）**

```bash
git add AGENTS.md
git commit -m "docs: AGENTS.md 补充 LLM provider 模板维护说明"
```

---

## 完成标准

- 后端：所有新测试 + 现有测试全绿；5 个新端点（templates / models / test 改造 / admin test / admin models）可用；`friendly_llm_error` 抽出共享；F1 修复。
- 前端：构建成功；5 个新组件 + 2 个页面重构；admin/用户两页视觉统一；模板/测试/拉模型三功能可用；默认态 accent 圆点；删除确认；enabled Switch。
- 手动 QA 清单全部通过。
- 所有改动原子提交，commit message 遵循现有风格（`type(scope): 中文描述`）。
