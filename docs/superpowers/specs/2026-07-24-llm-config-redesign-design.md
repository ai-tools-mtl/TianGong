# LLM 配置改造 — 设计契约

> 日期：2026-07-24
> 状态：待评审
> 范围：apps/api（后端）+ apps/web（前端）
> 相关文档：[MVP 设计](2026-07-13-tiangong-mvp-design.md) · [UI 重构契约](2026-07-14-ui-redesign-contract.md) · [AGENTS.md](../../../AGENTS.md)

## 一、背景与动机

天工当前的 LLM 配置有两个割裂的页面：

| 页面 | 路径 | 现状 |
|---|---|---|
| **admin 全局配置** | `/admin/console/llm` | 一个裸的内联表单 Card，**无测试按钮、无模型列表、无预设**，`enabled` 用原生 checkbox（与全局 pill 风格不统一） |
| **用户自定义配置** | `/settings` | 顶部一个独立 `SourceSelector`（radio 列表）+ 下方配置列表 + 创建/编辑两个 Dialog；**只有创建 Dialog 有测试按钮**，测试只验 chat 不验 embedding |

四个被频繁抱怨的痛点：
1. 配置 LLM 要手敲 `base_url`、模型名，没有「选个供应商模板自动填」。
2. 用户创建后能测，但 admin 全局配置**完全没法测**——配错了只能保存后到 AI 调用时才暴露。
3. 测试只覆盖 chat 模型，`embedding_model` 坏了要等到知识库 RAG 调用时才报错。
4. 模型名要纯手敲，没有「从供应商拉取可用模型列表」的能力。

此外交互语言上，两个页面用了**完全不同的组件词汇**（admin 是单 Card 表单；用户是 list+modal+radio），同一件事（配 LLM）长得不像。

## 二、目标与非目标

### 目标
1. **两个页面统一交互语言**：都走「unified panel 列表 + 内联展开编辑」的 Apple Liquid Glass 模式，共享同一套组件。
2. **provider 模板预设**：添加配置时可选预设（智谱 GLM / OpenAI / DeepSeek / OpenRouter / Ollama / 通用 OpenAI 兼容），自动填 `base_url` + 默认模型名。
3. **增强测试连接**：admin 全局补测试按钮；测试同时验证 chat 模型与 embedding 模型；返回延迟与友好错误。
4. **拉取模型列表**：调 provider 的 `/v1/models` 自动拉取可用模型，填入模型选择器（下拉选 + 可手输）。
5. 默认配置切换 UX 改为「每卡可设为默认 + accent 圆点徽章」，去掉顶部 radio。

### 非目标（本轮不做）
- **不做余额/额度查询**（DeepSeek `/user/balance`、智谱额度等）。原因：无通用接口，需 per-preset 适配，成本高收益窄。内部已有的 `LLMCallLog` 用量统计（`/admin/stats/llm`）不属本轮。
- **不动两层授权模型**（全局 Key + `UserGlobalLLMGrant` + 用户自定义配置）——这是承重墙，`source` 约定（`"global"` / `"custom:{id}"` / `"env"` / `None`）贯穿全调用链（5 个内部 caller + 所有 AI 路由），不重构。
- **不存「默认配置」到后端**——仍用 `localStorage`（`llm-source.ts`）。详见 §七·决策 D1。
- 不引入非 OpenAI 兼容协议（Anthropic 原生、Bedrock 等）。系统仍统一走 `ChatOpenAI` / `OpenAIEmbeddings`。`provider` 字段仍仅作展示。
- 不改 `get_llm` 的硬编码 `temperature=0.7`（不在本轮范围）。

### 附带修复（顺路，因都在同一文件/同一逻辑路径）
- **F1**：`conversation_service.summarize_conversation_title` 调 `get_llm(**{...})` 传错参数（`get_llm` 期望 `ResolvedLLMConfig` 位置参数），导致标题摘要始终静默 fallback。修掉。
- **F2**：用户删除自定义配置无确认（与项目删除流程 `delete-confirm-dialog.tsx` 不一致），本轮统一加确认。

## 三、设计原则（视觉/交互）

严格遵循 apple-liquid-glass 设计准则（5 条哲学：unified surface > fragmented cards / glass 只在图层重叠 / 克制即奢侈 / 层级靠字重灰阶不靠色 / 细节见品质）与天工现有 globals.css 的「墨黑 + 双层柔影 + 22px 圆角面板 + pill 按钮」token：

1. **Unified surface > fragmented cards**：配置列表是**一个白 panel + 发丝分隔（`rgba(0,0,0,0.07)`）**，不是一堆独立 border+底色的卡片。
2. **层级靠字重/灰阶/accent，不靠色块**：当前默认配置用「一个蓝色 accent 圆点 + 蓝色小徽章」表达，**不用深色填充/背景色**。
3. **Glass 只在图层重叠处**：内联展开面板用 `#fbfbfd` 浅灰底（非玻璃），测试结果区同理。只有确认删除等真·覆盖层才用玻璃 + dim scrim。
4. **Mapping**：测试/拉取/编辑按钮就挂在被影响的那一行/那个面板上，不弹远处的模态。
5. **反馈四态**：测试结果在线内联展示（status dot：`#30d158` 成功 / `#ea580c` 警告 / `#ff3b30` 失败 / `#d2d2d7` 未测）。

## 四、后端改动

### 4.1 新增 provider 模板静态数据（`apps/api/app/services/llm_provider_templates.py`）

**纯静态数据，无 DB、无 I/O。** 一份 provider 预设清单：

```python
@dataclass(frozen=True)
class ProviderTemplate:
    id: str                  # "zhipu" / "openai" / "deepseek" / "openrouter" / "ollama" / "custom"
    name: str                # 展示名：「智谱 GLM」
    base_url: str            # 默认 base_url
    default_model: str       # 默认 chat 模型名
    default_embedding_model: str | None  # 默认 embedding 模型名（Ollama 无）
    models_endpoint: str     # 拉模型的相对路径，如 "/v1/models"；Ollama 用 "/api/tags"
    docs_url: str | None     # 文档/官网链接（卡片底部「如何获取 API Key」）
    note: str | None         # 提示，如「智谱需要在开放平台开通模型」

PROVIDER_TEMPLATES: tuple[ProviderTemplate, ...] = (
    ProviderTemplate("zhipu",     "智谱 GLM",   "https://open.bigmodel.cn/api/paas/v4", "glm-4-plus", "embedding-3", "/v1/models", "https://open.bigmodel.cn", "智谱开放平台，需开通对应模型"),
    ProviderTemplate("deepseek",  "DeepSeek",   "https://api.deepseek.com",            "deepseek-chat",  None,        "/v1/models", "https://platform.deepseek.com", None),
    ProviderTemplate("openai",    "OpenAI",     "https://api.openai.com/v1",           "gpt-4o-mini",    "text-embedding-3-small", "/v1/models", "https://platform.openai.com/api-keys", None),
    ProviderTemplate("openrouter","OpenRouter", "https://openrouter.ai/api/v1",        "openai/gpt-4o-mini", None,     "/v1/models", "https://openrouter.ai/keys", None),
    ProviderTemplate("moonshot",  "Moonshot Kimi","https://api.moonshot.cn/v1",         "moonshot-v1-8k", None,        "/v1/models", "https://platform.moonshot.cn", None),
    ProviderTemplate("ollama",    "Ollama (本地)","http://localhost:11434",             "qwen2.5:7b",     "nomic-embed-text", "/api/tags", "https://ollama.com", "本地部署，无需 API Key"),
    ProviderTemplate("custom",    "自定义（OpenAI 兼容）", "", "", None, "/v1/models", None, "填写你的 OpenAI 兼容端点"),
)
```

**端点**：`GET /api/v1/settings/llm/templates`（`get_current_user`）→ 返回 `list[ProviderTemplateOut]`。
- `ProviderTemplateOut` schema 字段同上（去掉内部用不到的）。
- admin 与普通用户都走这个端点（admin 在 `/admin/console/llm` 也用它）。

> 决策 D2：模板数据放后端而不是前端硬编码。理由：① base_url/默认模型可能随供应商调整，后端改一处即可；② 未来若要按租户/环境注入不同模板集（内网部署常需自定义中转网关），后端是唯一可扩展点。前端不该藏业务默认值。

### 4.2 增强测试连接：`POST /api/v1/settings/llm/test`（改造现有端点）

**改造现有** `apps/api/app/api/settings.py:test_my_llm`（L121-139）。现状：只测 chat、吞所有异常返 200、不测 embedding。

新行为：
```python
class UserLLMTestRequest(BaseModel):
    base_url: str
    api_key: str
    model: str = Field(..., min_length=1)
    embedding_model: str | None = None   # 现在真的会测

@router.post("/settings/llm/test")
def test_my_llm(payload, current_user):
    """测试连通性：chat 必测；embedding_model 提供则一并测。不落库、不写 LLMCallLog（与现状一致）。"""
    result = llm_config_service.test_llm_connection(
        base_url=payload.base_url, api_key=payload.api_key,
        model=payload.model, embedding_model=payload.embedding_model,
    )
    return result  # TestConnectionResult
```

返回结构 `TestConnectionResult`（service 层产出）：
```python
{
  "ok": True|False,
  "chat": {"ok": bool, "latency_ms": int|None, "sample": str|None, "error": str|None},
  "embedding": {"ok": bool, "latency_ms": int|None, "dim": int|None, "error": str|None} | None,
  "error": str|None  # 顶层兜底错误（如 base_url 连不上）
}
```

测试逻辑（service 新函数 `test_llm_connection`）：
- **chat**：`ChatOpenAI(...).invoke([HumanMessage("hi")])`，记录耗时；成功则 `sample = resp.content[:50]`。
- **embedding**（仅当 `embedding_model` 非空）：`OpenAIEmbeddings(...).embed_query("hi")`，记录耗时与向量维度 `dim = len(vec)`。
- 两个测试独立 try/except，互不影响（chat 失败仍可测 embedding，反之亦然）。
- 错误信息走 `_friendly_llm_error`（`api/ai.py` L97-119 已有的友好化映射）——**抽到 service/util 共享**，不复制。
- **超时**：每个测试包 `httpx` 级超时 15s（通过 `ChatOpenAI(request_timeout=15)` / `OpenAIEmbeddings(request_timeout=15)`）。避免智谱偶发卡死拖死前端。
- 顶层 `ok = chat.ok and (embedding_model is None or embedding.ok)`。

> 抽函数：`_friendly_llm_error` 从 `api/ai.py` 移到 `app/services/llm_errors.py`（或 `app/ai/errors.py`），`api/ai.py` 和 `test_llm_connection` 都 import 它。避免逻辑分裂。

### 4.3 新增 admin 全局配置测试：`POST /api/v1/admin/llm-config/test`（新端点）

admin 全局配置现状**完全无测试**。新增：

```python
@router.post("/admin/llm-config/test")
def test_global_llm(payload: GlobalLLMTestRequest, _: User = Depends(require_admin)):
    """admin 测试全局配置连通性。支持两种模式：
    - 传入完整字段（base_url/api_key/model/embedding_model）：用传入值测，不落库（保存前预检）。
    - 不传 base_url/api_key（留空）：用 SystemSetting 里已存的（解密后）测（保存后复检）。
    """
```

`GlobalLLMTestRequest`（admin/console.py，与 `GlobalLLMSettings` 对齐）：
```python
class GlobalLLMTestRequest(BaseModel):
    base_url: str | None = None        # None = 用已存的
    api_key: str | None = None         # None = 用已存的（解密）
    model: str | None = None
    embedding_model: str | None = None
```

逻辑：
- 若 `base_url`/`api_key`/`model` 任一为空 → 从 `SystemSetting.llm_global_config` 读取（`api_key_encrypted` 解密），用存档值测。
- 否则用传入值测（与用户侧 test 一致，调用同一个 `test_llm_connection`）。
- 返回同样的 `TestConnectionResult`。

> 决策 D3：admin 端点独立而非复用 `/settings/llm/test`，因为：① 权限不同（`require_admin` vs `get_current_user`）；② admin 有「用已存值测」的复检模式，用户侧不需要（用户侧 key 不回查明文，无法复检）。共享的是 **service 函数** `test_llm_connection`，端点本身分开。

### 4.4 新增拉取模型列表：`POST /api/v1/settings/llm/models`（新端点）

```python
class ListModelsRequest(BaseModel):
    base_url: str
    api_key: str
    provider_template_id: str | None = None  # 用于决定 endpoint 路径（Ollama 用 /api/tags）

@router.post("/settings/llm/models")
def list_provider_models(payload, current_user):
    """调 provider 的模型列表端点，返回可用模型名数组。不落库。"""
    return llm_config_service.list_provider_models(
        base_url=payload.base_url, api_key=payload.api_key,
        provider_template_id=payload.provider_template_id,
    )  # {"models": ["glm-4-plus", "glm-4-flash", ...], "truncated": bool, "error": str|None}
```

service 新函数 `list_provider_models`：
- **endpoint 解析**：若 `provider_template_id` 给出且为 `ollama`，用 `{base_url}/api/tags`；否则用 `{base_url}/v1/models`（兼容智谱/OpenAI/DeepSeek/OpenRouter，它们都是 OpenAI 兼容的 `/v1/models`）。
- **请求**：直接用 `httpx`（不绕 LangChain），`GET {endpoint}` 带 `Authorization: Bearer {api_key}`，超时 15s。
- **解析**：OpenAI 兼容格式 `{"data": [{"id": "...", ...}]}` → 取 `id`；Ollama 格式 `{"models": [{"name": "..."}]}` → 取 `name`。
- **截断**：返回前 100 条，`truncated=True` 表示还有更多（避免某些供应商返回上千条）。
- **错误**：base_url 不通/401/格式异常 → `{"models": [], "error": "友好错误"}`，**不抛 500**（前端要能展示「拉取失败」而不是崩）。
- **去重 + 排序**：模型名去重后按字母序。

> 决策 D4：用 `httpx` 直连而非 LangChain。理由：LangChain 没有标准的「列模型」抽象（`ChatOpenAI.get_available_models` 这类方法行为不稳定、版本间变），而 `/v1/models` / `/api/tags` 是稳定的 HTTP 协议。直连也更省依赖、更易测。

### 4.5 admin 端拉模型：`POST /api/v1/admin/llm-config/models`（新端点）

与 4.4 同理，权限 `require_admin`，复用 `list_provider_models`。admin 全局配置编辑时也要能拉模型。

### 4.6 附带修复 F1：`conversation_service.summarize_conversation_title`

`services/conversation_service.py` L26-36：把 `get_llm(base_url=..., api_key=..., model=...)` 改为先 `resolve_llm_config(...)` 拿到 `ResolvedLLMConfig` 再 `get_llm(llm_config)`。修复后对话标题摘要才真正生效。

## 五、前端改动

### 5.1 共享组件：`apps/web/src/components/llm-config/`（新建目录）

把两个页面共用的部分抽成组件，单一真相源：

| 组件 | 职责 |
|---|---|
| `ProviderTemplatePicker.tsx` | 模板 chip 条（横向滚动），点选后回调填充 base_url/默认模型 |
| `LLMConfigRow.tsx` | 列表中的一行（名称 / 模型 chip / Key 掩码 / 状态点 / 默认徽章 / 操作按钮）。prop: `isDefault`, `onSetDefault`, `onEdit`, `onDelete`, `onTest` |
| `LLMConfigEditPanel.tsx` | **内联展开**的编辑/新增面板。包含：模板 picker、名称、base_url、api_key（眼睛切换）、对话模型（下拉+手输+拉取按钮）、embedding 模型（同）、测试按钮+结果区、保存/取消 |
| `ModelSelectInput.tsx` | 「下拉选 + 可手输」的模型输入。下拉数据来自拉取结果；手输直接打字（自由文本） |
| `TestResultBadge.tsx` | 测试结果四态展示（status dot + 文字 + 延迟） |

这些组件**两个页面共用**。差异通过 props 注入（如 admin 面板多一个 `allowedModels` 编辑框）。

### 5.2 用户页 `/settings` 重构

**去掉** `SourceSelector`（顶部 radio 列表）。默认配置状态融进每个 `LLMConfigRow`：
- 当前默认行：标题左侧 `accent-dot` + 右侧蓝色「默认」徽章。
- 非默认行：右侧「设为默认」ghost pill。
- 全局 Key 不作为列表行显示（它不是用户的「配置」，而是授权态）——它的「是否作为默认」通过页面顶部一段**简短说明 + 一个 toggle** 表达：「使用全局 Key 作为默认（需被授权）」。这个 toggle 仍写 `localStorage`（`llm-source.ts`）。

页面结构（自上而下）：
1. `PageHeader`：标题「LLM 配置」+ 右上「+ 添加配置」按钮（pill primary）。
2. **全局 Key 说明条**（条件渲染：用户已被授权时显示）：一行灰底说明「你已被授权使用全局 Key」+ 一个 toggle「作为默认」。
3. **unified panel**（白底 + 发丝分隔）：每个自定义配置一行 `LLMConfigRow`。点「+ 添加」或某行「编辑」→ 该位置**内联展开** `LLMConfigEditPanel`（其余行可见、可滚动）。
4. 空态：`EmptyState`「暂无配置，点击右上角添加」。

数据流不变：`useQuery(['my-llm'])` → `api.listMyLLM()`；默认 source 仍 `localStorage`。删除加 `ConfirmDialog`（F2）。

### 5.3 admin 页 `/admin/console/llm` 重构

admin 全局配置只有**一个**配置（全局 Key），所以页面是**单个 `LLMConfigEditPanel` 的特化**：
- 顶部 `PageHeader`：标题「全局 LLM 配置」+ 描述。
- **enabled toggle**：把原生 `<input type="checkbox">` 换成手写的 pill 式开关（项目无 shadcn Switch，手写一个，遵循 GOTCHAS F8）。
- 下方直接是 `LLMConfigEditPanel`（`providerTemplatePicker` / base_url / api_key 留空=不改 / 对话模型 / embedding 模型 / **allowed_models** 编辑框 / 测试按钮 + 结果 / 保存）。
- 「测试」支持两种模式：保存前用表单当前值测；保存后用「已存值复检」（对应后端 §4.3 的留空模式）——通过一个「用已存配置测试」次级按钮表达。

admin 页**不**有「设为默认」（admin 默认就是全局），**不**有 `LLMConfigRow` 列表（只有一个配置）。

### 5.4 API client & types（`apps/web/src/lib/api.ts` + `types/api.ts`）

新增：
```ts
// api.ts
export const listProviderTemplates = () => api.get<ProviderTemplate[]>('/settings/llm/templates')
export const listProviderModels = (b: {base_url, api_key, provider_template_id?}) =>
  api.post<{models: string[], truncated: boolean, error: string | null}>('/settings/llm/models', b)
// 测试端点签名扩展（返回 TestConnectionResult）
export const testMyLLM = (b) => api.post<TestConnectionResult>('/settings/llm/test', b)
// admin 新增
export const testGlobalLLM = (b) => api.post<TestConnectionResult>('/admin/llm-config/test', b)
export const listGlobalProviderModels = (b) => api.post<...>('/admin/llm-config/models', b)

// types/api.ts
export interface ProviderTemplate { id; name; base_url; default_model; default_embedding_model; models_endpoint; docs_url; note }
export interface TestConnectionResult { ok; chat: {ok, latency_ms, sample, error}; embedding: {...} | null; error }
```

React Query 包装加到 `lib/queries.ts`（`useProviderTemplates`、`useProviderModels`、`useTestLLMConnection`）。

### 5.5 `llm-source.ts` 小改

新增 `isGlobalDefault()` / `setGlobalDefault(bool)` 便捷函数（仍写同一个 localStorage key，值为 `"global"` 或清空），供 §5.2 的 toggle 用。现有 `getDefaultSource/setDefaultSource/clearDefaultSource` 保留兼容。

## 六、数据流与状态

### 测试连接流程（用户侧，内联展开面板）
```
点「测试连接」(按钮)
  → useTestLLMConnection.mutate({base_url, api_key, model, embedding_model})
  → POST /settings/llm/test
  → service.test_llm_connection(...)
    ├ chat: ChatOpenAI.invoke("hi")  [15s timeout]
    └ embedding: OpenAIEmbeddings.embed_query("hi")  [15s timeout]
  → TestConnectionResult
  → 前端 TestResultBadge 展示 chat/embedding 各自状态 + 延迟
```
测试是**独立的探索动作**，不触发保存、不 invalidate 列表（测试的是表单当前值，非已存值）。

### 拉取模型流程
```
点对话模型旁「⤓ 拉取」
  → useProviderModels.mutate({base_url, api_key, provider_template_id})
  → POST /settings/llm/models
  → service.list_provider_models(...)
  → {models: [...], truncated, error}
  → ModelSelectInput 下拉数据更新；error 时下拉空 + 顶部红字提示
用户在下拉里选 / 或直接手输 → 填入 model 字段
```
拉取结果**只存组件本地 state**，不持久化（每次进面板重拉；避免缓存了已下线的模型）。

### 默认配置切换
```
点某行「设为默认」
  → setDefaultSource(`custom:${id}`)  // localStorage
  → 本地 state 更新，重渲染：该行加 accent-dot + 默认徽章，其余行变回「设为默认」按钮
  → 若之前默认是全局 Key，全局 toggle 自动关掉（互斥）
```
**不调后端**（D1）。换设备/浏览器默认值不同步——接受。

## 七、关键决策记录

- **D1（默认配置不持久化到后端）**：保持 `localStorage`。天工是内部产品、单人单浏览器场景为主，多设备同步的收益不抵加字段+迁移+端点的成本。若未来要同步，最小改动是给 `SystemSetting` 加一个 `user_default_llm_source` map 或 user 表加列，届时再做。
- **D2（模板数据放后端）**：见 §4.1。前端不藏业务默认值。
- **D3（admin test 端点独立）**：见 §4.3。权限与「用已存值复检」模式不同，端点分开但共享 service 函数。
- **D4（拉模型用 httpx 直连）**：见 §4.4。绕开 LangChain 不稳定的列模型抽象。
- **D5（模型选择 = 下拉 + 手输，不改数据模型）**：每个 config 仍只存一个 `model` + 一个 `embedding_model`（现状）。拉取结果只作下拉建议项，不落库。避免了「多选启用模型」要改表的大动作。
- **D6（API Key 仍只掩码，不查明文）**：安全优先。复用现有 `_mask_key`（`llm_config_service.py`）：首 3 + `****` + 尾 4（如 `sk-****abcd`）；Key 长度 ≤ 8 时全显示为 `****`（避免短 key 被猜）。表单输入框默认隐藏 + 眼睛图标临时显示明文；保存后不回显明文；编辑时 api_key 留空 = 不改。admin 也不能查明文（与现状一致）。

## 八、错误处理

| 场景 | 行为 |
|---|---|
| 测试 chat 失败、embedding 成功 | `ok=False`，但 `chat.error` 有值、`embedding.ok=True`；前端分别展示 |
| 拉模型 401 | `error="API Key 无效或无权限"`，`models=[]`；前端下拉空 + 红字 |
| 拉模型 base_url 不通 | `error="无法连接到 {base_url}"`；同上 |
| 拉模型超时（>15s） | `error="拉取超时，请检查网络或端点"`；同上 |
| 拉模型返回非预期格式 | `error="响应格式无法解析"`；同上 |
| 模板端点查无（不该发生） | 返回空数组，前端 chip 条空 + 手动填写 |
| admin 测试用已存值但全局配置未填全 | `error="全局配置未设置完整（缺 model/api_key）"` |
| 删除配置 | 加 `ConfirmDialog`（F2），确认后调 DELETE |
| 测试/拉取进行中 | 按钮置 disabled + spinner；不阻塞其他行操作 |

所有面向用户的错误都经过 `_friendly_llm_error` 映射（智谱 1214 / 401 / 超时 / 连接错误 → 中文友好提示）。

## 九、测试

### 后端 pytest（`apps/api/tests/`）
- `test_provider_templates.py`：`PROVIDER_TEMPLATES` 完整性（每条字段非空、id 唯一、`custom` 必须在列）；`GET /settings/llm/templates` 鉴权与返回结构。
- `test_llm_test_connection.py`：mock `ChatOpenAI.invoke` / `OpenAIEmbeddings.embed_query`，覆盖：chat 成功+embedding 成功、chat 失败+embedding 成功、都失败、embedding_model=None 只测 chat、超时路径、友好错误映射。
- `test_list_provider_models.py`：mock `httpx`，覆盖 OpenAI 格式、Ollama `/api/tags` 格式、401、超时、非预期格式、>100 条截断、去重排序。
- `test_admin_global_test.py`：admin 鉴权（非 admin 403）；用传入值测；用已存值测（mock SystemSetting 读取+解密）；全局配置未填全的错误。
- F1 修复回归：`test_conversation_title_summarize.py` 验证 `summarize_conversation_title` 真正调用 LLM 生成标题（mock `get_llm`，断言被调用且参数正确）。

> 用 SQLite 内存库 + mock 外部 HTTP（httpx / langchain），不真实调供应商。遵循 GOTCHAS G2。

### 前端
- 组件单测（如有 vitest）：`LLMConfigEditPanel` 的模板 picker 回调、`ModelSelectInput` 下拉+手输、`TestResultBadge` 四态。
- 手动 QA 清单（写入 plan，非自动化）：① admin 与用户两页面视觉一致；② 6 个模板逐个选→base_url/模型自动填；③ 智谱真 key 测 chat+embedding 全绿；④ 故意填错 key 测→友好错误；⑤ Ollama `/api/tags` 拉模型；⑥ 内联展开/收起不丢其他行状态；⑦ 设为默认互斥（含全局 toggle）；⑧ 删除确认弹窗。

## 十、迁移与兼容

- **无 DB 迁移**（本轮不碰表结构）。`provider` 字段仍存 `"custom"` 默认值，模板 id **不入库**（只在前端表单态用）——决策 D5 的体现。
- **API 兼容**：`POST /settings/llm/test` 返回结构从 `{ok, response|error}` 变为 `TestConnectionResult`（结构更丰富）。这是**不兼容变更**，但调用方只有前端一处（`settings/page.tsx` CreateDialog），同批改造，可接受。后端测试同步更新。
- **localStorage 兼容**：`tg_default_llm_source` key 不变，`getDefaultSource` 等函数签名不变，新增的 `isGlobalDefault/setGlobalDefault` 是便捷封装。

## 十一、风险与回滚

- **风险 1：provider 实际 `/v1/models` 行为差异**。智谱、某些中转可能不返回标准 OpenAI 格式或限流。**缓解**：拉取失败时 `error` 兜底 + 前端允许手输，不阻断配置流程。模板里 `models_endpoint` 字段为未来 per-provider 适配留口。
- **风险 2：内联展开在小屏推挤布局**。**缓解**：`LLMConfigEditPanel` 用响应式 grid（`grid-cols-2` → `grid-cols-1` @ 680px），移动端面板占满宽度。
- **风险 3：测试/拉取真打到供应商计费**。chat 测 "hi" 约 1-2 token、embedding 测 "hi" 约 1 token，成本可忽略；但 Ollama 本地无成本。文档里说明。
- **回滚**：前端改动是新增组件 + 重构两个页面，git revert 即可；后端新端点删除、`test` 端点回退到旧签名+旧逻辑。无 DB 迁移意味着无回滚迁移负担。

## 十二、不做清单（防止 scope creep）

- ❌ 余额/额度查询（DeepSeek balance、智谱额度）
- ❌ 多模型勾选启用（每个 config 仍单 model + 单 embedding_model）
- ❌ 非 OpenAI 兼容协议（Anthropic 原生 / Bedrock / Vertex）
- ❌ 默认配置后端持久化
- ❌ `get_llm` 的 temperature/max_tokens/top_p 参数化
- ❌ API Key 明文回查（含 admin）
- ❌ 配置导入/导出 / 分享链接（cc-switch 的 deep-link，本轮不要）
- ❌ 拖拽排序配置

## 十三、文件清单（实施时按此落地）

**后端（apps/api/）**
- 新增 `app/services/llm_provider_templates.py`
- 新增 `app/ai/errors.py`（从 `api/ai.py` 抽 `_friendly_llm_error`）
- 改 `app/services/llm_config_service.py`：加 `test_llm_connection`、`list_provider_models`
- 改 `app/api/settings.py`：改 `test_my_llm`、加 `/settings/llm/templates`、`/settings/llm/models`
- 改 `app/api/admin/console.py`：加 `/admin/llm-config/test`、`/admin/llm-config/models`
- 改 `app/services/conversation_service.py`：F1 修复
- 新增/改测试：见 §九

**前端（apps/web/src/）**
- 新增 `components/llm-config/ProviderTemplatePicker.tsx`
- 新增 `components/llm-config/LLMConfigRow.tsx`
- 新增 `components/llm-config/LLMConfigEditPanel.tsx`
- 新增 `components/llm-config/ModelSelectInput.tsx`
- 新增 `components/llm-config/TestResultBadge.tsx`
- 新增 `components/ui/switch.tsx`（手写，pill 式开关，GOTCHAS F8）
- 改 `app/(app)/settings/page.tsx`：去 SourceSelector、接入新组件
- 改 `app/(app)/admin/console/llm/page.tsx`：enabled toggle 换 switch、接入 EditPanel、加测试
- 改 `lib/api.ts`、`types/api.ts`、`lib/queries.ts`：新增端点与类型
- 改 `lib/llm-source.ts`：加 `isGlobalDefault`/`setGlobalDefault`
