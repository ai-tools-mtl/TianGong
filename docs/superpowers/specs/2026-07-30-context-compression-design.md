# 对话上下文压缩 —— 设计文档

> 日期：2026-07-30
> 状态：待评审
> 范围：天工 AI agent 的对话历史压缩（章节 chat/generate + 项目初始化助手两条路径）

## 1. 背景与动机

### 1.1 现状（已查证）

天工调用 LLM 时，对话历史在两条路径上的处理不同：

| 路径 | 调用链 | 历史取数 | 压缩兜底 |
|---|---|---|---|
| **A. 章节 chat/generate** | `ai.py` → `orchestrator.astream_chat/astream_generate` → `build_agent` → `create_deep_agent` | `_get_section_with_history`（`ai.py:40-54`）无 `.limit()`，全量取 | deepagents 默认 `SummarizationMiddleware`（黑盒：170k token 触发 / 留最近 6 条 / GLM 无 profile 时硬编码） |
| **B. 项目初始化助手** | `init_assistant.py` → `init_orchestrator.astream_init_chat` → 裸 `astream_llm` | `_get_init_history`（`init_assistant.py:51-60`）无 `.limit()`，全量取 | **无任何兜底**，超长直接报 provider token 超限 |

关键证据：
- `_get_section_with_history`（`app/api/ai.py:44-53`）：`select(Message)...order_by(Message.created_at)`，无 limit。
- `astream_chat`（`app/ai/orchestrator.py:142-145`）：`for msg in history: messages.append(...)`，全量透传。
- `build_agent`（`app/ai/agent.py:114-121`）：`create_deep_agent(...)` 不传 `middleware=`/`excluded_middleware=`，蹭库默认中间件。
- init 助手 `_build_init_chat_messages`（`app/ai/init_orchestrator.py:52-61`）：`SystemMessage + 全部 history + 当前输入`，无截断；`astream_init_generate`（`init_orchestrator.py:139-141`）对每个章节都重灌完整历史。
- 项目自身代码全局搜索 `trim_messages` / `ConversationBufferMemory` / `max_tokens` / `tiktoken` 等：**零命中**（命中的 `summarize_conversation_title` 是会话起标题，与历史压缩无关）。

### 1.2 问题

1. **路径B 无兜底**：超长对话直接崩，用户体验差。
2. **路径A 黑盒不可控**：deepagents 默认中间件阈值（170k/留6条）对 GLM 是硬编码，天工无法配置、无日志、无观测；出问题时无法定位是否压缩导致。
3. **两路径行为不一致**：维护与排查成本高。

### 1.3 关于「仿照 ZCode 压缩算法」

需求原始表述为「仿照 ZCode 的上下文压缩算法」。经核实：ZCode 的压缩逻辑在其**私有运行时**中，本地（`~/.zcode/cli`）仅有会话产物（`rollout/`、`artifacts/sess_*`）和插件，**无任何压缩算法的可读源码或文档**。ZCode 系统提示对其压缩的描述仅为行为级一句话（"对话变长时自动总结成 summary + 保留剩余未压缩上下文"），不含算法细节。

因此本设计**不绑定 ZCode 的具体实现**，而是基于成熟的对话压缩通用范式（双闸触发 / 首尾保留 + 中段摘要 / 运行时压缩不污染原始数据 / 摘要落盘可观测）+ 天工实际架构来设计。这是在无法核实外部依据时的诚实取舍。

## 2. 设计目标与非目标

### 2.1 目标
- **G1 一致性**：两条路径（章节 chat/generate + init 助手）共用同一套压缩逻辑、同一套阈值。
- **G2 可控**：压缩阈值/保留策略由天工自己集中配置（`BudgetConfig`），不依赖 deepagents 黑盒默认。
- **G3 可观测**：每次压缩生成 `Snapshot`，关键字段持久化到 `LLMCallLog.context_meta`，管理后台可查。
- **G4 不污染原始数据**：`Message` 表永远是完整原始消息；压缩仅在「装配给 LLM 前」发生。
- **G5 容错**：压缩是旁路行为，其运行时失败不阻断主对话（分类降级，见 §5.2）。

### 2.2 非目标（YAGNI）
- 不做消息内分块（单条极长消息整体进中段或尾部，MVP 不切分）。
- 不做增量/持久化压缩缓存（每次请求独立计算，接受重复算的代价）。
- 不自研复杂的多级摘要调度器（单层一次性摘要即可）。
- 不替换 deepagents 的其他中间件（仅排除其 SummarizationMiddleware）。

## 3. 架构（第 1 节）

### 3.1 模块边界

新增模块：`apps/api/app/ai/context_compactor.py`

**职责单一**：输入 `(history: list[Message], current_input, llm_config, budget)` → 输出 `(compressed_messages: list[dict], snapshot: Snapshot)`。纯函数式 + 一个异步摘要调用，不直接碰数据库（摘要用的 `get_llm` 经 llm_config 间接走配置）。

**暴露两层 API**：
```python
# 高层：给 orchestrator 用
async def compress_history(
    history: list[Message], current_input: str, llm_config: ResolvedChatConfig,
    *, scene: str = "chat",
) -> tuple[list[dict], Snapshot]: ...

# 低层：纯函数，给测试用（不调 LLM）
def estimate_tokens(text: str) -> int: ...
def should_compress(history_count: int, est_tokens: int, budget=BudgetConfig) -> bool: ...
```

### 3.2 数据流

```
Message 表（全量原始，永不被改）
   │  ai.py: _get_section_with_history 取数（保持不变，仍取全量）
   ▼
history: list[Message]
   │  新增：orchestrator / init_orchestrator 装配前调 compactor
   ▼
compress_history(history, current_input, llm_config, budget)
   │
   ├─ 不触发 → 原样转 dict 返回，Snapshot(triggered=False)
   └─ 触发   → 首条user + [摘要] + 最近N条 + 当前输入
   ▼
compressed_messages  ← list[dict]（含一条 role=user 的摘要消息）
   │  喂给 agent.astream_events / astream_llm
   ▼
LLM
```

**关键设计决策**：压缩发生在**装配层**，**不改取数层**（`_get_section_with_history` / `_get_init_history` 仍取全量）。这样「用户前端看历史 = 完整原始」「LLM 看历史 = 压缩版」分离清晰，且与天工既有装配模式（`assemble_messages` / `build_system_prompt` 本就是运行时装配、不落库）一致。

## 4. 压缩算法（第 2 节）

### 4.1 预算配置（BudgetConfig，模块顶部常量，可调）

```python
@dataclass(frozen=True)
class BudgetConfig:
    # 双闸阈值（任一命中即触发）
    max_messages: int = 30          # 条数快闸
    token_budget: int = 24000       # token 慢闸（GLM 128k 窗口的 ~18%，留余量给 system prompt + 输出）
    # 保留策略
    keep_head: int = 1              # 保留首条 user（原始需求）
    keep_tail: int = 10             # 保留最近 10 条

DEFAULT_BUDGET = BudgetConfig()
```

### 4.2 触发判定（双闸 OR）

```python
def should_compress(history_count: int, est_tokens: int, budget=DEFAULT_BUDGET) -> bool:
    # 连首尾都凑不齐，无中段可压
    if history_count <= budget.keep_head + budget.keep_tail:
        return False
    if history_count > budget.max_messages:      # 条数闸
        return True
    if est_tokens > budget.token_budget:         # token 闸
        return True
    return False
```

### 4.3 轻量 token 估算（无 tiktoken）

GLM 用不了 tiktoken 的 cl100k 编码（本身也是近似），且引入 tiktoken 增加依赖与计数开销。采用混合字符加权近似：

```python
def estimate_tokens(text: str) -> int:
    """混合文本 token 近似。中文 ~1.5 字/token，英文/标点 ~4 字符/token。
    精度 ±25%，配合条数闸兜底，不会明显误判触发。"""
    # 按 unicode 字符是否为 CJK 分别计数后加权求和
    ...
```
对消息列表：`sum(estimate_tokens(m.content) for m in messages)`。

### 4.4 压缩主流程

```python
async def compress_history(history, current_input, llm_config, *, scene="chat", budget=DEFAULT_BUDGET):
    est_tokens = estimate_tokens_list(history) + estimate_tokens(current_input)
    if not should_compress(len(history), est_tokens, budget):
        return to_dicts(history), Snapshot(triggered=False, reason="uncompressed",
                                            original_count=len(history), ...)

    head = history[:budget.keep_head]
    middle = history[budget.keep_head:-budget.keep_tail]
    tail = history[-budget.keep_tail:]

    summary = await summarize(middle, llm_config)   # 见 §4.5，失败抛 SummarizeRuntimeError

    compressed = []
    for m in head:
        compressed.append({"role": m.role, "content": m.content})
    # 摘要消息：role=user + 明确前缀（见 §6.3 决策）
    compressed.append({
        "role": "user",
        "content": f"[早期对话历史摘要，共{len(middle)}条已归档]\n{summary}"
    })
    for m in tail:
        compressed.append({"role": m.role, "content": m.content})

    # reason 取实际触发的闸：条数优先（"messages>30"），否则 "tokens>24000"
    reason = "messages>30" if len(history) > budget.max_messages else "tokens>24000"
    return compressed, Snapshot(triggered=True, reason=reason,
                                 original_count=len(history), compressed_count=len(compressed),
                                 middle_count=len(middle), est_tokens_before=est_tokens,
                                 est_tokens_after=estimate_tokens_list_dicts(compressed),
                                 fallback=False)
```

### 4.5 摘要生成（分类降级，见 §5.2）

```python
class SummarizeRuntimeError(Exception): ...

async def summarize(messages: list[Message], llm_config) -> str:
    # 配置类错误：直接抛（由调用方决定，但属"该报的错"）
    if not llm_config or not llm_config.model:
        raise ValueError("LLM 配置缺少 model，无法生成摘要")  # 配置类，不降级
    try:
        llm = get_llm(llm_config, streaming=False)
        resp = await llm.ainvoke([SystemMessage(SUMMARIZE_PROMPT),
                                  HumanMessage(format_for_summary(messages))])
        text = resp.content.strip()
        if not text:
            raise SummarizeRuntimeError("摘要返回空")
        return text
    except SummarizeRuntimeError:
        raise
    except Exception as e:
        # 运行时错误（超时/限流/网络）→ 转成 SummarizeRuntimeError，由 compress_history 捕获降级
        raise SummarizeRuntimeError(str(e)) from e
```

**摘要 prompt（专利交底书场景特调）**：
```
SUMMARIZE_PROMPT = """你是对话历史压缩器。把多轮对话压缩成一段高密度摘要，供 AI 撰写助手延续上下文。

必须保留（缺一不可）：
1. 用户确定的技术问题、技术方案、关键术语（原词不换同义词）
2. 已达成的结论、用户明确表达的偏好或约束
3. 待解决/未确定的开放问题

可以省略：寒暄、重复内容、已被后续对话推翻的旧说法。

输出要求：纯文本摘要（不要 Markdown 标题），300 字以内。只输出摘要，不要解释。"""
```

## 5. 可观测性、降级与边界（第 3 节）

### 5.1 Snapshot 结构与持久化

```python
@dataclass
class Snapshot:
    triggered: bool
    reason: str            # "uncompressed" / "messages>30" / "tokens>24000" / "fallback_truncate" / "summarize_failed"
    original_count: int
    compressed_count: int
    middle_count: int
    est_tokens_before: int
    est_tokens_after: int
    fallback: bool = False
```

- **日志**：调用方始终打 `logger.info`（触发）/ `logger.debug`（未触发），含关键字段。
- **持久化**：`Snapshot` 序列化进 `LLMCallLog.context_meta`（新增 JSON 字段，nullable）。需加 Alembic 迁移。写入点在现有 LLMCallLog 记账处（`llm_log_helper.py` / `ai.py` usage 落账处）。管理后台可查每次调用的压缩情况。

### 5.2 降级链（分类降级，绝不盲目阻断主流程）

| 失败类型 | 处理 | 理由 |
|---|---|---|
| 配置类（无 `llm_config` / `model` 空） | **抛错**（ValueError） | 配置问题，本就该在 `check_tool_support` 等更早闸口拦截；用户需知情 |
| 摘要运行时失败（超时/限流/网络/返回空） | **降级**：硬截断保首+尾，丢弃中段，`Snapshot.fallback=True, reason="summarize_failed"`，打 warning 日志 | 旁路调用失败不应炸主请求；硬截断后对话仍可继续 |
| 连尾部都超 token 预算（极端） | **降级②**：只留首 + 尾的最后几条 | 保不住也不报 token 超限崩掉 |

**铁律**：`compress_history` 对运行时失败永不向主流程抛异常；最坏情况是"信息有损但对话能继续"。配置类错误例外（该报则报）。

`compress_history` 内部捕获 `SummarizeRuntimeError` 并转降级路径：
```python
    try:
        summary = await summarize(middle, llm_config)
    except SummarizeRuntimeError:
        # 降级①：硬截断保首尾，中段丢弃
        compressed = to_dicts(head) + to_dicts(tail)
        return compressed, Snapshot(triggered=True, reason="summarize_failed",
                                     ..., fallback=True)
    except ValueError:
        raise  # 配置类错误，向上抛
```

### 5.3 边界情况

| 情况 | 处理 |
|---|---|
| history 为空 | 直接返回，不压缩 |
| history ≤ keep_head+keep_tail | `should_compress` 已挡，不触发 |
| 中段只有 1-2 条 | 仍摘要（一致性优先，不为特例开分支） |
| 单条消息极长 | token 闸触发；该条整体进中段或尾部，MVP 不分块 |
| 消息顺序异常 | 信任 `_get_section_with_history` 的 `created_at` 排序 |
| 摘要返回空/乱码 | 视为 `SummarizeRuntimeError`，走降级① |
| 并发同会话多次请求 | 无状态压缩，每次独立计算，无竞态（接受重复算代价） |

## 6. 接入点（第 4 节）

### 6.1 路径A：章节 chat/generate

**接入点 1 — `app/ai/orchestrator.py`**：
- `astream_chat`（当前 142-145 行全量灌）改为：
  ```python
  compressed, snapshot = await compress_history(history, user_input, llm_config, scene="chat")
  logger.info("context compress (chat): %s", asdict(snapshot))
  messages = compressed  # 已含首+摘要+尾+当前输入
  ```
- `astream_generate`（当前 204-208 行）同样改造，压缩后再 append generate 指令。

**接入点 2 — `app/ai/agent.py` 的 `build_agent`**：
- `create_deep_agent`（114-121 行）新增 `excluded_middleware` 关掉库默认 SummarizationMiddleware，避免双重压缩。
- **待验证项**：`excluded_middleware` 的确切签名（类名字符串 vs 类型对象），实现时查 deepagents 源码定。若该库不支持排除，回退方案：保留库默认但把天工自己的压缩作为"预处理"（库中间件在已压缩的更短历史上几乎不会再触发，可接受）。

### 6.2 路径B：项目初始化助手

**接入点 3 — `app/ai/init_orchestrator.py`**：
- `_build_init_chat_messages`（当前 52-61 行）改为先压缩：
  ```python
  compressed, snapshot = await compress_history(history, user_input, llm_config, scene="init")
  messages = [SystemMessage(content=INIT_SYSTEM_PROMPT)] + to_langchain_messages(compressed)
  ```
- `astream_init_generate`（139-141 行）：每个章节生成都先压缩历史，token 开销大降（这是原最危险点）。

### 6.3 摘要消息的 role 决策

经讨论定：摘要消息用 **`role=user` + 明确前缀**（`[早期对话历史摘要，共N条已归档]\n...`），而非 `role=system`。理由：agent 框架（deepagents/LangGraph）对"消息序列中间夹 system 消息"的兼容性不一致，某些框架会把非首 system 当 user 处理或合并；用 user+前缀最稳，无兼容风险。

### 6.4 LLMCallLog 加字段

- **迁移**：`LLMCallLog` 加 `context_meta`（JSON，nullable）。
- **写入**：snapshot → dict → `context_meta`。init 助手若不记 LLMCallLog 则至少打 logger。

## 7. 测试策略（第 5 节）

TDD（遵循 superpowers:test-driven-development）。三层：

### 7.1 单元测试 `tests/test_context_compactor.py`（纯逻辑，mock LLM，SQLite 内存库 + 真实 Message，遵循 GOTCHAS G2）

| 用例 | 验证点 |
|---|---|
| `test_should_compress_short_history` | ≤首尾凑不齐 → 不触发，原样返回 |
| `test_should_compress_by_message_count` | 31 条 token 不超 → 触发（条数闸） |
| `test_should_compress_by_tokens` | 5 条但单条极长超 budget → 触发（token 闸） |
| `test_compress_keeps_head_and_tail` | 触发后 messages[0]==首条user、末尾==当前输入、中间含摘要 |
| `test_estimate_tokens_chinese_vs_english` | 中文权重高于英文 |
| `test_summarize_success` | mock LLM 返回 → 摘要出现、fallback=False |
| `test_summarize_runtime_failure_falls_back` | mock 超时 → 降级硬截断、fallback=True、reason=summarize_failed |
| `test_summarize_config_error_raises` | model 空 → 抛 ValueError（配置类不降级） |
| `test_compress_never_raises_on_edge` | 空/单条/中段1条 → 都不抛 |
| `test_snapshot_fields_complete` | 触发的 snapshot 字段非 None |

### 7.2 集成测试 `tests/test_orchestrator_compression.py`

- `test_astream_chat_compresses_long_history`：35 条历史 → SSE 流收到 token、snapshot 记录。
- `test_init_orchestrator_compresses`：init 长历史 → 压缩后被调用。

### 7.3 TDD 节奏

1. `estimate_tokens` / `should_compress`（纯函数）
2. `compress_history` 不触发分支（无 LLM）
3. `summarize` + 降级（mock LLM）
4. `compress_history` 触发分支
5. orchestrator / init_orchestrator 接入

### 7.4 不测
- 真实 GLM 调用（mock 即可）
- deepagents 中间件排除的真实生效（标为实现后手动验证项，依赖库版本）

## 8. 实现顺序（给 writing-plans 的输入）

1. 新建 `context_compactor.py`：`BudgetConfig` + `estimate_tokens` + `should_compress` + `Snapshot`（纯逻辑，先 TDD 过）。
2. `summarize` + `SummarizeRuntimeError`（mock LLM，TDD）。
3. `compress_history` 完整流程（触发/不触发/降级三分支，TDD）。
4. 加 `LLMCallLog.context_meta` 迁移 + 写入。
5. 接入 orchestrator（chat/generate）。
6. 接入 init_orchestrator。
7. `build_agent` 排除 deepagents SummarizationMiddleware（验证 API 签名）。
8. 手动验证：长对话场景跑通 + 后台可见 context_meta。

## 9. 已知限制与待验证

- **L1**：token 估算精度 ±25%（轻量近似的代价，由条数闸兜底）。
- **L2**：每次请求独立重算压缩，无缓存（YAGNI，MVP 接受）。
- **L3**：单条极长消息不分块（整体进中段或尾部）。
- **V1（待验证）**：deepagents `excluded_middleware` 的确切 API；若不支持，回退到"预处理 + 保留库默认"。
- **V2（待验证）**：路径A 压缩后 messages 灌进 `agent.astream_events` 的兼容性（摘要用 role=user 已规避主要风险）。
