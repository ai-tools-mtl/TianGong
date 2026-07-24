# LLM chat / embedding 独立凭据改造 — 设计契约

> 日期：2026-07-24
> 状态：待评审
> 范围：apps/api（后端）+ apps/web（前端）
> 相关：[LLM 配置改造（上一轮，已合并）](2026-07-24-llm-config-redesign-design.md) · [MVP 设计](2026-07-13-tiangong-mvp-design.md)
> 项目阶段声明：开发阶段，DB 表结构未最终定稿，可直接改（D3 据此简化迁移）

## 一、背景与动机

上一轮 LLM 配置改造（已合并到 main）交付了模板预设、增强测试、拉模型列表、两页统一 UI。但**底层 chat 与 embedding 仍共用同一套凭据**：`ResolvedLLMConfig` 一个 dataclass 同时承载 `base_url`/`api_key`（chat+embedding 共用）+ `model`（chat）+ `embedding_model`（embedding）；`UserLLMConfig` 一张表一套 key。

这导致一个硬约束：**用户无法让 chat 用一个供应商、embedding 用另一个**（例如智谱 chat + OpenAI embedding）。这是真实的跨供应商混搭需求。

本设计把 chat 与 embedding 拆成两套**完全独立**的凭据链路：独立表、独立 dataclass、独立解析函数、独立 source 协议维度、独立默认选择。

**顺路净简化**：删除 `GlobalLLMSettings.allowed_models`（纯展示字段，从无强制校验）。

## 二、目标与非目标

### 目标
1. **chat 与 embedding 凭据彻底分离**：两套独立的表、dataclass、resolve 路径、source 维度。
2. **跨供应商混搭成立**：chat 用供应商 A、embedding 用供应商 B 在同一请求内可同时工作。
3. **两套独立默认源**：用户分别选默认 chat 源、默认 embedding 源。
4. 删除 `allowed_models`（净简化）。
5. embedding 调用补 `LLMCallLog` 日志（action="embed"），让调用统计能区分 chat/embedding。

### 非目标（本轮不做）
- ❌ 不做 admin grant 拆分（一个 grant 仍同时覆盖全局 chat + 全局 embedding，D5）。
- ❌ 不做"每次对话也选 embedding_source"——rag_search 工具走 fallback（YAGNI，§4.3）。
- ❌ 不保留 `ResolvedLLMConfig` 兼容层（直接删，rename 全代码库）。
- ❌ 不保留老迁移数据（开发阶段，D3）。
- ❌ 不引入非 OpenAI 兼容协议。
- ❌ 不做配置导入/导出、多模型勾选等（沿用上一轮非目标）。

## 三、承重决策（D1-D6）

- **D1（独立表 + source 双值）**：新建 `UserEmbeddingConfig` 表；`UserLLMConfig` 删 `embedding_model` 列；前端发 `chat_source` + `embedding_source` 两个独立值；localStorage 存两个 key。
- **D2（chat 与 embedding 各自独立选默认）** ⚠️经用户确认：用户在设置页选两个独立默认源（默认 chat 源 + 默认 embedding 源），各可选 global / custom-chat:{id} / custom-emb:{id} / env。两套独立 toggle 组，互不影响。
- **D3（开发阶段迁移：纯 schema 变更，不保数据）** ⚠️经用户确认：当作开发阶段、表结构可塑。迁移只做"建新表 + 删老列"，不写数据搬运。老库的测试/手填配置丢弃，用户重建。`init_db.py` seed 同步改成 seed 一条 chat + 一条 embedding。
- **D4（fallback 不互通）** ⚠️经用户确认：chat fallback 与 embedding fallback 两条路径**完全独立**。embedding 没配 → `resolve_embedding_config` 返回 None → caller 报清晰错误，**不隐式回退到 chat 凭据**（消除现状的耦合根源）。这是行为变化：现状 embedding 没配会隐式用 chat 凭据跑 embedding。
- **D5（admin grant 不拆）**：`UserGlobalLLMGrant` 仍按用户单一授权，一个 grant 同时覆盖全局 chat + 全局 embedding。无 grant 表迁移。
- **D6（allowed_models 删除）**：删 `GlobalLLMSettings.allowed_models`（前后端、schema、相关测试），删 `LLMConfigEditPanel.adminMode` + 那个输入框（adminMode 失去唯一用途，面板统一）。
- **D7（embedding 调用加日志）** ⚠️默认做（用户可在评审时去掉）：embedding caller 在 embed 后写一条 `LLMCallLog(action="embed", ...)`，让 admin 调用统计区分 chat/embedding。

## 四、数据模型与迁移

### 4.1 `UserLLMConfig`（改：删 embedding_model 列）
```python
class UserLLMConfig(Base, IdMixin, TimestampMixin):
    __tablename__ = "user_llm_configs"
    user_id:   Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name:      Mapped[str] = mapped_column(String(50))
    provider:  Mapped[str] = mapped_column(String(50), default="custom")
    base_url:  Mapped[str] = mapped_column(String(255))
    api_key_encrypted: Mapped[str] = mapped_column(String(512))
    model:     Mapped[str] = mapped_column(String(100))
    # embedding_model 列删除（移到新表）
```
现在这张表纯粹是 **chat 配置**。

### 4.2 `UserEmbeddingConfig`（新建表，与 chat 表对称）
```python
class UserEmbeddingConfig(Base, IdMixin, TimestampMixin):
    __tablename__ = "user_embedding_configs"
    user_id:   Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name:      Mapped[str] = mapped_column(String(50))           # 如「智谱 embedding」
    base_url:  Mapped[str] = mapped_column(String(255))
    api_key_encrypted: Mapped[str] = mapped_column(String(512))
    model:     Mapped[str] = mapped_column(String(100))          # embedding 模型名
```
与 chat 表**完全对称**（同样列结构），语义是 embedding。故意不复用一张表+type 字段——这样 `custom-chat:{id}` 与 `custom-emb:{id}` 的 source 命名空间天然分离，授权/CRUD 互不干扰。

### 4.3 迁移（开发阶段，纯 schema 变更，不保数据 — D3）
新建 alembic revision `b_split_embedding_config.py`：
```python
def upgrade():
    op.create_table("user_embedding_configs", ...)  # 与 user_llm_configs 同构（id/user_id/name/base_url/api_key_encrypted/model + 时间戳）
    op.drop_column("user_llm_configs", "embedding_model")
def downgrade():
    op.add_column("user_llm_configs", sa.Column("embedding_model", sa.String(100), nullable=True))
    op.drop_table("user_embedding_configs")
```
**不写数据搬运**。开发库现有配置丢弃，用户重建。`init_db.py` 的 seed 改成：seed admin 时建一条 chat 配置 + 一条 embedding 配置（都默认智谱 glm）。

### 4.4 全局配置 JSON 拆两套（SystemSetting，schema-less 无迁移）
| key | 现状 | B 之后 |
|---|---|---|
| `llm_global_enabled` | `{"enabled":bool}` | 不变 |
| `llm_global_config` | `{base_url, api_key_encrypted, model, embedding_model, allowed_models}` | **拆** → `llm_global_chat_config` `{base_url, api_key_encrypted, model}` |
| `llm_global_embedding_config` | (不存在) | **新建** `{base_url, api_key_encrypted, model}` |
| ~~allowed_models~~ | 在 `llm_global_config` 里 | **删除**（D6） |

老的 `llm_global_config` key 迁移时忽略（开发阶段，admin 重新配）。代码读取新两个 key。

## 五、解析函数与 source 协议

### 5.1 数据类拆两个（删 ResolvedLLMConfig）
```python
@dataclass
class ResolvedChatConfig:
    base_url: str
    api_key: str
    model: str
    source: str = "user"        # "user" / "global" / "env" / "admin"

@dataclass
class ResolvedEmbeddingConfig:
    base_url: str
    api_key: str
    model: str
    source: str = "user"
```
原 `ResolvedLLMConfig`（含 embedding_model）**直接删除**（D：不留兼容层）。chat 类不再有 embedding_model 字段，消除耦合根源。全代码库 rename。

### 5.2 source 协议：单值 → 双值
| | 现状 | B 之后 |
|---|---|---|
| 前端发（chat/generate/rewrite/caption 端点） | `source: str \| None` | `chat_source: str \| None` |
| localStorage | `tg_default_llm_source`（1 个） | `tg_default_chat_source` + `tg_default_embedding_source`（2 个） |
| 取值空间 | `"global"` / `"custom:{id}"` / `"env"` / `None` | chat: `"global"` / `"custom-chat:{id}"` / `"env"` / `None`<br>embedding: `"global"` / `"custom-emb:{id}"` / `"env"` / `None` |

source 前缀从 `custom:` 拆成 `custom-chat:` / `custom-emb:`，命名空间天然分离。

### 5.3 两个解析函数（完全独立）
```python
def resolve_chat_config(db, *, user_id, chat_source=None) -> ResolvedChatConfig | None:
    """chat_source 取值：global / custom-chat:{id} / env / None(内部 fallback)"""

def resolve_embedding_config(db, *, user_id, embedding_source=None) -> ResolvedEmbeddingConfig | None:
    """embedding_source 取值：global / custom-emb:{id} / env / None(内部 fallback)"""
```
两函数独立——不共享代码路径、不互相兜底（D4）。各自的 global 分支读各自的 JSON key、各自的 custom 分支读各自的表、各自的 env 分支读各自的 settings 字段。

### 5.4 内部 caller fallback（无前端 source）
5 个内部 caller 调 `resolve_*(db, user_id)` 不传 source，走 fallback。按调用方分两组：
| caller | 调 | fallback 顺序（D4） |
|---|---|---|
| `review_service` `summary_service` `conversation_service.title` | `resolve_chat_config` | admin→global chat→env；非 admin→grant→global chat→最早 chat 配置→env |
| `rag/archiver` `rag/retriever` `knowledge_service` `tools.rag_search`(chat 内) | `resolve_embedding_config` | admin→global embedding→env；非 admin→grant→global embedding→最早 embedding 配置→env |

**两条 fallback 不互通**。embedding 没配返回 None → caller 报清晰错误「未配置 embedding，无法做 RAG/向量化」，不隐式用 chat 凭据（D4 行为变化）。

### 5.5 `_build_*` 辅助函数拆对
```python
def _build_global_chat_config(db, *, source) -> ResolvedChatConfig | None       # 读 llm_global_chat_config
def _build_global_embedding_config(db, *, source) -> ResolvedEmbeddingConfig | None  # 读 llm_global_embedding_config
def _build_env_chat_config() -> ResolvedChatConfig | None       # 读 glm_base_url/glm_api_key/glm_model
def _build_env_embedding_config() -> ResolvedEmbeddingConfig | None  # 读 glm_base_url/glm_api_key/glm_embedding_model
def _resolve_chat_fallback(db, *, user, user_id) -> ...
def _resolve_embedding_fallback(db, *, user, user_id) -> ...
```
现状的 `_build_global_config` / `_build_env_config` / `_resolve_fallback` 各拆成 chat/embedding 一对。env 那对读同一个 `glm_*` 设置（chat 读 `glm_model`，embedding 读 `glm_embedding_model`）——env 兜底默认仍智谱一套。

## 六、API 端点

### 6.1 用户侧 chat 端点（改造现有 `/settings/llm/*`）
| 端点 | 现状 | B 之后 |
|---|---|---|
| `GET /settings/llm` | 列 chat 配置（含 embedding_model） | 列 chat 配置（**去掉** embedding_model 字段） |
| `POST /settings/llm` | 建（含 embedding_model） | 建（**去掉** embedding_model 入参） |
| `PUT /settings/llm/{id}` | 改 | 改（去掉 embedding_model） |
| `DELETE /settings/llm/{id}` | 删 | 不变 |
| `POST /settings/llm/test` | 测 chat + 可选 embedding | **只测 chat**（`TestConnectionResult` 类型不变，但本端点只填 `chat` 子对象，`embedding` 字段恒为 `null`） |
| `POST /settings/llm/models` | 拉模型 | 不变 |
| `GET /settings/llm/templates` | 模板列表 | 不变 |

### 6.2 用户新增 embedding 端点（镜像 chat 一套，`/settings/embedding/*`）
| 端点 | 作用 |
|---|---|
| `GET /settings/embedding` | 列当前用户的 embedding 配置 |
| `POST /settings/embedding` | 建 |
| `PUT /settings/embedding/{id}` | 改（所有权校验，越权 404） |
| `DELETE /settings/embedding/{id}` | 删 |
| `POST /settings/embedding/test` | 测 embedding 连通（只测 embedding；`TestConnectionResult` 类型不变，本端点只填 `embedding` 子对象，`chat` 字段恒为 `null`） |
| `POST /settings/embedding/models` | 拉模型 |

操作 `UserEmbeddingConfig` 表，鉴权 `get_current_user`，与 chat 端点同构。**故意镜像一套而非参数化**（如 `/settings/llm?type=embedding`）——source 命名空间、表、CRUD 逻辑都独立，参数化反而耦合。

### 6.3 admin 全局端点（改造 + 拆）
| 端点 | 现状 | B 之后 |
|---|---|---|
| `GET /admin/llm-config` | `{llm_global_enabled, global_config:{..., allowed_models}}` | `{llm_global_enabled, chat_config:{base_url,api_key_masked,model}, embedding_config:{...}}`（**删 allowed_models**） |
| `PUT /admin/llm-config` | 存一套 | 存两套（chat_config + embedding_config 独立字段，各自可只传一个改一半） |
| `POST /admin/llm-config/test` | 测一套（支持用已存值复检） | **删除**，由下面两个取代 |
| `POST /admin/llm-config/models` | 拉一套 | **删除**，由下面两个取代 |
| `POST /admin/llm-config/chat/test` | (新) | 测全局 chat（支持用已存值复检，路径 `/admin/llm-config/chat/test`） |
| `POST /admin/llm-config/embedding/test` | (新) | 测全局 embedding（支持用已存值复检） |
| `POST /admin/llm-config/chat/models` | (新) | 拉全局 chat 模型 |
| `POST /admin/llm-config/embedding/models` | (新) | 拉全局 embedding 模型 |
| grant 端点 `/admin/users/{id}/global-llm-grant` | 授权/撤销 | **不变**（D5） |

> 决策：admin test/models **拆两个端点**（不参数化 `?scope=`），与用户侧两套端点的对称性一致。老的单个 `/admin/llm-config/test` 和 `/admin/llm-config/models` 端点**删除**（被四个新端点取代），前端同批改。

## 七、前端

### 7.1 共享面板 `LLMConfigEditPanel`（去 adminMode + allowed_models — D6）
去掉 `adminMode` prop 和 allowed_models 输入框。面板字段只剩：`name / base_url / api_key / model / 模板 / 测试 / 拉模型`。chat 和 embedding 各用一个实例，复用度提高。

### 7.2 `/settings` 页拆两区
```
设置页
├─ 全局授权说明条（chat 与 embedding 共用一个 grant，文字说明）
├─ 【对话模型配置】区
│   ├─ chat 默认源 toggle 组（global / custom-chat:{id}）
│   ├─ chat 配置列表（LLMConfigRow × N，内联展开 LLMConfigEditPanel）
│   └─ + 添加 chat 配置
├─ 【嵌入模型配置】区  ← 新增区
│   ├─ embedding 默认源 toggle 组（global / custom-emb:{id}）
│   ├─ embedding 配置列表（EmbeddingConfigRow × M，内联展开 LLMConfigEditPanel）
│   └─ + 添加 embedding 配置
└─ 我的技能 入口卡片（不动）
```
两区视觉对称（沿用上一轮 unified panel + accent 圆点语言）。`EmbeddingConfigRow` 是 `LLMConfigRow` 的镜像（同结构，数据源不同）。

### 7.3 `/admin/console/llm` 拆两区
```
admin 全局配置页
├─ enabled Switch（两套全局共用）
├─ 【全局对话模型】区（LLMConfigEditPanel 实例 × 1，常驻）
└─ 【全局嵌入模型】区（LLMConfigEditPanel 实例 × 1，常驻）
```
+ 顶部「用已存配置测试」拆成 chat 复检 / embedding 复检两个按钮。

### 7.4 localStorage 与默认源 UI（D2）
`llm-source.ts` 改：
- `tg_default_llm_source` → `tg_default_chat_source` + `tg_default_embedding_source`
- `getDefaultSource/setDefaultSource/clearDefaultSource` → 拆 chat 版和 embedding 版
- `isGlobalDefault/setGlobalDefault` → 拆 chat 版和 embedding 版

两套独立 toggle，各自可选 global / 某条 custom。chat 选默认不影响 embedding，反之亦然（D2）。

## 八、内部 caller 改造

### 8.1 chat 侧 caller（4 处，纯 rename + 类型换，无行为变化）
| 文件 | 现状 | B 之后 |
|---|---|---|
| `api/ai.py`（4 端点 L204/300/382/601） | `resolve_llm_config(db, user_id, source=payload.source)` | `resolve_chat_config(db, user_id, chat_source=payload.chat_source)` |
| `services/review_service.py`（L45） | `resolve_llm_config(db, user_id=user_id)` | `resolve_chat_config(db, user_id=user_id)` |
| `services/summary_service.py`（L33） | `resolve_llm_config(db, user_id=project.user_id)` | `resolve_chat_config(db, user_id=project.user_id)` |
| `services/conversation_service.py`（标题） | 入参 `llm_config: ResolvedLLMConfig` | 改 `ResolvedChatConfig` |

`get_llm(llm_config)` 签名改成 `get_llm(chat_config: ResolvedChatConfig)`。

### 8.2 embedding 侧 caller（4 处，切独立路径）
| 文件 | 现状 | B 之后 |
|---|---|---|
| `rag/archiver.py`（L20,43） | `embed_config = resolve_llm_config(...)` → `embed_texts(...)` | `resolve_embedding_config(...)` → `get_embedder` 收 `ResolvedEmbeddingConfig` |
| `rag/retriever.py`（L34,37） | 同上 | 同上 |
| `services/knowledge_service.py`（L252,257） | 同上 | 同上 |
| `ai/tools.py` 的 `rag_search_tool` | 调 `retrieve(...)` 间接解析 | 不直接改（`retrieve` 内部已切） |

`get_embedder`/`embed_text`/`embed_texts`（`rag/embedding.py`）签名从 `ResolvedLLMConfig` 改 `ResolvedEmbeddingConfig`，读 `.base_url/.api_key/.model`（不再有 `.embedding_model`）。

### 8.3 chat 内 rag_search 的两次解析（核心 invariant）
一个 chat 请求里两次独立解析：
```
POST /sections/{id}/chat (chat_source=custom-chat:abc)
  → resolve_chat_config(user_id, "custom-chat:abc")  → ResolvedChatConfig → build_agent → ChatOpenAI
    → agent 循环触发 rag_search 工具
      → retrieve(db, user_id, query)
        → resolve_embedding_config(user_id)  # 无 source,fallback
        → embed_text → OpenAIEmbeddings
```
两次解析完全独立，各查各的表/JSON。chat 用智谱、embedding 用 OpenAI 在同一请求里成立——这是 B 的核心价值。rag_search 工具拿不到前端选的 embedding_source（不在 chat 请求上下文），只能走 fallback（用户预设的默认 embedding）。这是设计上接受的（YAGNI：让用户每次对话也选 embedding_source 是另一个故事）。

### 8.4 embedding 调用加日志（D7）
`archiver`/`retriever`/`knowledge_service` 在 `embed_texts`/`embed_text` 后写一条 `LLMCallLog(action="embed", model=embed_config.model, provider=embed_config.source, status=...)`。失败也写（status="failed"）。chat 侧日志不变。

## 九、错误处理

| 场景 | 行为 |
|---|---|
| embedding 没配（无自定义、未被授权全局、env 也没） | `resolve_embedding_config` 返回 None → caller 抛清晰错误「未配置 embedding 模型，请在设置页『嵌入模型配置』区添加」 |
| chat 没配 | `resolve_chat_config` 返回 None → caller 抛「未配置对话模型」（沿用现状语义） |
| 越权访问 embedding 配置（custom-emb:{别人id}） | `NotFoundError`（404，防探测，与 chat 侧一致） |
| 测试 embedding 连接失败 | `TestConnectionResult`（简化版，只有 chat 那部分结构，字段名沿用）友好错误 |
| admin 全局 chat 配了但 embedding 没配 | 半态：chat 走全局、embedding 走各自的 fallback（可能 env 或报错）。grant 是一个但配置是两套，各自独立判断。 |

## 十、测试策略

### 后端 pytest（SQLite 内存库 + mock，GOTCHAS G2）
- `test_chat_config_resolution.py`：`resolve_chat_config` 全分支（global / custom-chat:{id} / env / fallback / 越权 404）。镜像现有 `test_global_llm_config.py` 的 resolve 测试。
- `test_embedding_config_resolution.py`：`resolve_embedding_config` 全分支（对称）。
- `test_embedding_config_crud_api.py`：`/settings/embedding/*` 一整套端点（CRUD + test + models + 鉴权）。镜像现有 `test_llm_config_endpoints.py`。
- `test_chat_embedding_independence.py`：**核心 invariant 测试**——构造"chat 配置 base_url A、embedding 配置 base_url B"，mock `ChatOpenAI`/`OpenAIEmbeddings`，断言两者收到不同 base_url。
- `test_fallback_no_crosstalk.py`：embedding 没配 → `resolve_embedding_config` 返回 None → caller 报错，**不**回退 chat 凭据（D4 回归守护）。
- 改造现有 `test_global_llm_config.py` / `test_llm_config_endpoints.py` / `test_llm.py` / `test_conversation_title.py`：适配新类型名（`ResolvedChatConfig`）、去掉 `embedding_model` 入参、新 source 前缀（`custom-chat:`）。
- `test_internal_callers_switched.py`：确认 `archiver`/`retriever`/`knowledge_service`/`review`/`summary` 都调了正确的 resolve 函数（mock resolve_chat/resolve_embedding，断言 caller 调对）。

### 前端
- `pnpm build` 必须干净（types/api.ts 新 `UserEmbeddingConfig`/`EmbeddingConfigRow` 等类型）。
- 手动 QA 清单（写进 plan，非自动化）：① /settings 两区视觉对称 ② chat 与 embedding 各自 CRUD/测试/拉模型 ③ 各自选默认源互不影响 ④ chat 用智谱 + embedding 用 OpenAI 端到端跑通（chat 对话 + 知识库 RAG 都正常）⑤ admin 两套全局配置独立 ⑥ 删 allowed_models 后 admin 面板无该字段。

## 十一、迁移与兼容

- **DB 迁移**：4.3 的纯 schema 变更（建新表 + 删老列）。`init_db.py` seed 改：seed admin 一条 chat + 一条 embedding（都默认智谱）。
- **API 兼容**：多处响应结构变（chat 配置去 embedding_model、test 去 embedding 字段、global 拆两套、source 前缀变）。**全部不兼容**——调用方只有前端（同批改）和内部 caller（同批改），无外部消费者，可接受。
- **localStorage**：`tg_default_llm_source` 旧 key 直接废弃（用户重选），不写迁移逻辑（开发阶段）。

## 十二、风险与回滚

| 风险 | 缓解 |
|---|---|
| 改动面大（20+ 文件），易漏 caller | 实施时 grep 全代码库 `resolve_llm_config`/`ResolvedLLMConfig`/`embedding_model`/`embed_config`，逐一确认；`test_internal_callers_switched.py` 兜底 |
| embedding 没配导致 RAG 报错（D4 行为变化） | 错误信息清晰；`init_db.py` seed 默认 embedding，新部署开箱即用 |
| chat 内 rag_search 拿不到 embedding_source | 设计上接受走 fallback（8.3），文档说明 |
| `ResolvedLLMConfig` 删除波及面 | 故意不留兼容层；rename 全代码库，编译/测试即暴露遗漏 |
| 回滚 | 后端有迁移（downgrade 重建老列 + 删新表）；前端 git revert；无外部 API 消费者，回滚无负担 |

## 十三、文件清单（实施时按此落地）

**后端（apps/api/）**
- 新增 `app/models/user_embedding_config.py`（新表）
- 改 `app/models/__init__.py`（导出 `UserEmbeddingConfig`）
- 改 `app/models/user_llm_config.py`（删 embedding_model 列）
- 新增 alembic revision（建新表 + 删老列）
- 改 `app/services/llm_config_service.py`（核心重写：拆 dataclass、resolve、build、fallback、CRUD、global settings；删 allowed_models）
- 改 `app/ai/llm_client.py`（`get_llm` 收 `ResolvedChatConfig`）
- 改 `app/rag/embedding.py`（`get_embedder` 等收 `ResolvedEmbeddingConfig`）
- 改 `app/api/ai.py`（4 端点用 `chat_source` + `resolve_chat_config`）
- 改 `app/api/settings.py`（chat 端点去 embedding_model；新增 `/settings/embedding/*` 端点）
- 改 `app/api/admin/console.py`（global 拆两套；test/models 拆两套；删 allowed_models）
- 改 `app/services/conversation_service.py`（类型换）
- 改 `app/services/review_service.py` / `summary_service.py`（改调 `resolve_chat_config`）
- 改 `app/rag/archiver.py` / `retriever.py`、`app/services/knowledge_service.py`（改调 `resolve_embedding_config` + 加 embed 日志）
- 改 `app/services/stats_service.py`（如有：统计按 action 区分 chat/embedding 展示）
- 改 `scripts/init_db.py`（seed chat + embedding 两条）
- 新增/改测试（见 §十）

**前端（apps/web/src/）**
- 改 `types/api.ts`（新 `UserEmbeddingConfig` 等；`GlobalLLMSettings` 拆；删 allowed_models）
- 改 `lib/api.ts`（新 embedding 端点 client；test 响应去 embedding 字段；global 拆）
- 改 `lib/queries.ts`（新 embedding hooks）
- 改 `lib/llm-source.ts`（拆双 key + 双函数）
- 改 `components/llm-config/LLMConfigEditPanel.tsx`（去 adminMode + allowed_models）
- 新增 `components/llm-config/EmbeddingConfigRow.tsx`（镜像 LLMConfigRow）
- 改 `app/(app)/settings/page.tsx`（拆两区）
- 改 `app/(app)/admin/console/llm/page.tsx`（拆两区 + test/models 拆）
