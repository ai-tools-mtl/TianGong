# 天工 Agent Skill 管理模块 — 设计契约（grill 结论）

> 本文档由 `/grill-me` 设计访谈产生（2026-07-22，6 轮质询），记录「Agent Skill 管理模块」的全部架构决定与回溯依据。
> **实施记录详见：** `plans/2026-07-22-agent-skills.md`
> **前置阅读：** `AGENTS.md` · `docs/GOTCHAS.md` · 设计文档 §7.4（旧 skill 定义，将被取代）

---

## 锚点总览

Agent Skills 开放标准 · 两档可见性（admin 全局 / 用户个人）· MinIO `BaseStore` 适配 · deepagents 全量重写 AI 层 · 自建 Docker sandbox · BYOK 不支持 tool calling 时拒绝服务 · 旧 `agent_skills` 表彻底删除。

---

## 1. 背景与目标

### 1.1 为什么做这个模块

天工目前的「能力扩展」机制是 `agent_skills` 表（`project_id` + `skill_key` + `enabled` + `config`）+ `seed_service.BUILTIN_SKILLS` 硬编码常量。它的契约是「技能定义是代码常量，项目只能开关/配置」，5 个内置 skill（`rag_search`/`rubric_review`/`consistency_check`/`quality_report`/`prior_art_hint`）里只有 `rag_search` 有真实运行时代码路径（`orchestrator._retrieve_knowledge` 的布尔守卫），其余 4 个是纯 UI 元数据。

这套机制无法让 admin/用户自定义技能、无法让技能被 agent 真正按需消费、不符合行业开放标准。

### 1.2 目标

引入 **Agent Skills 开放标准**（[agentskills.io](https://agentskills.io/specification)，Apache 2.0 / CC-BY-4.0，2025-12 Anthropic 发布），建成：

1. **两档可见性**的技能管理体系：admin 全局（全站可见）+ 用户个人（仅本人）。
2. **spec 合规的真 agent**：agent 能按需读 `SKILL.md`（三层渐进式披露），能在 sandbox 里跑用户脚本。
3. **彻底删除**旧的 `agent_skills` 表 + 项目级 skill 耦合。

### 1.3 非目标（本契约范围外）

- 移动端 / 平板 UI（沿用现有 PC 端统一面板布局）。
- 多租户组织级 skill（`org_admin` 角色预留但不在本模块实现）。
- skill 市场 / 发布流程（grill Q17-b 正式撤回 Q7-iii，只有两档可见性，无 public 档）。

---

## 2. Agent Skills 开放标准要点（事实地基）

来源：[agentskills.io specification](https://agentskills.io/specification) · [Anthropic 工程博客](https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills) · [Claude Platform Docs](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview)

| 要素 | 约束 |
|---|---|
| **目录结构** | 一个 skill = 一个目录，最少含 `SKILL.md`；可选 `scripts/`（Python/Bash/JS）、`references/`、`assets/` |
| **`SKILL.md`** | YAML frontmatter（`name`+`description` 必填）+ Markdown 正文 |
| **`name`** | 1–64 字符，`[a-z0-9-]`，不能首尾/连续连字符，**必须等于父目录名** |
| **`description`** | 1–1024 字符，单行——**不是给人看的，是 agent 的触发条件**（什么任务该激活我）|
| **三层渐进式披露** | L1 启动时只加载所有 skill 的 `name+description`（~100 tokens/个）→ L2 agent 决定激活后读 `SKILL.md` 正文（<5000 tokens / <500 行）→ L3 按需读 `scripts/`/`references/`/`assets/` |

---

## 3. 决定矩阵（含 grill 回溯）

每个决定标注 grill 轮次，可回溯到质询过程。

| 维度 | 决定 | grill | 否决项 / 理由 |
|---|---|---|---|
| **skill 定义** | Agent Skills 开放标准 `SKILL.md` 目录 | Q1 | 否决"prompt 文本片段"(c)：要 spec 合规 |
| **旧体系** | `agent_skills` 表 + 项目耦合**彻底删除** | Q2/Q5 | 否决"重定义为项目启用清单"：彻底解耦，项目无 skill 状态 |
| **AI 运行时** | **路线 B**：全量切 `deepagents`，spec 合规三层披露 | Q8/Q10/Q16 | 否决"路线 A prompt 注入"：抛弃渐进式披露=spec 残缺 |
| **默认模型** | `glm-4.7`（V1 验证通过，[Coding Plan 默认](https://docs.bigmodel.cn/cn/coding-plan/overview)）| Q14(i) | base_url 不变 `open.bigmodel.cn/api/paas/v4`，只改默认 model 名 |
| **BYOK 降级** | **(α) 拒绝服务**：模型不支持 tool calling → 明确报错 | Q14(ii) | 否决"静默降级路线 A"(β)：隐性降级是产品事故温床；否决"假装能跑"(γ) |
| **存储** | MinIO + 自写 LangGraph `BaseStore` 适配器 | Q4/Q9 | `StoreBackend` 包它，`SkillsMiddleware` 加载 |
| **可见性** | 两档：admin 全局 + 用户个人 | Q7/Q17b | 撤回"其他用户公开 skill"(iii)：删发布流程，无 public 档 |
| **合并方式** | **纯运行时计算**可见集合 | Q11-α | 项目无 skill 状态，下线即不可见，无孤儿问题 |
| **脚本执行** | 支持（spec L3）| Q12-b | 用户脚本跑在隔离 sandbox |
| **sandbox 落地** | sandbox **直读 MinIO**（Q15-A）+ **自建 Docker**（V3 验证）| Q15 | 否决 E2B 自托管（[e2b-dev/infra](https://github.com/e2b-dev/infra) 需 Kubernetes/Firecracker，对个人项目过度）；否决 LangSmith Sandbox（$1.50/LCU 按秒计费）|
| **写交底书流** | **全量切 deepagents agent loop** | Q16-A | 否决"双轨"：两套 AI 调用路径维护成本翻倍，且 skill 不进主流程则无意义 |

---

## 4. V1–V3 工程验证结论（2026-07-22 验证通过）

| # | 验证项 | 结论 | 证据 |
|---|---|---|---|
| V1 | glm-4.7 在 `open.bigmodel.cn/api/paas/v4` 的合法性 | ✅ 真实存在，SWE-bench 73.8% | [Coding Plan 概览](https://docs.bigmodel.cn/cn/coding-plan/overview)；标准 API endpoint 可用，base_url 无需改 |
| V2 | Python ≥3.11（deepagents 硬要求）| ✅ `Python 3.14.6` | `uv run python --version`；`pyproject.toml` 已含 `langgraph>=1.2.9` |
| V3 | sandbox 方案 | ✅ 自建 Docker（`docker` Python SDK）| E2B 自托管过度；LangSmith 按秒计费 |

**补充验证项（实施时第一 Task 执行）**：
- `pip install deepagents` 可装（[deepagents PyPI](https://pypi.org/project/deepagents/)，Python <4.0）。
- `langgraph` 与 `deepagents` 版本兼容矩阵确认。

---

## 5. 数据模型

### 5.1 新表 `skills`

```python
# apps/api/app/models/skill.py
class Skill(Base, IdMixin, TimestampMixin):
    __tablename__ = "skills"
    name: Mapped[str]              # spec name, [a-z0-9-], ≤64, 必须等于 MinIO 目录名
    description: Mapped[str]       # Text, ≤1024, 单行（spec 约束，触发条件）
    scope: Mapped[str]             # "global" | "personal"（两档可见性）
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)  # global=NULL
    status: Mapped[str]            # "draft" | "active"，draft 不进 runtime
    minio_prefix: Mapped[str]      # "skills/global/<name>/" 或 "skills/personal/<owner_id>/<name>/"
```

- `scope` + `owner_id` 联合表达可见性：`scope="global"` 时 `owner_id=NULL`；`scope="personal"` 时 `owner_id` 必填。
- `status="draft"` 的 skill 不进 runtime（admin/用户编辑中内容不喂 agent）。
- `minio_prefix` 是 MinIO 对象前缀，skill 的 `SKILL.md`+`scripts/`+`references/`+`assets/` 都挂在这个前缀下。
- 唯一约束（partial index）：SQL 标准里 NULL 视为 distinct，单一 `(scope, owner_id, name)` 复合唯一索引对 global 档（`owner_id` 恒为 NULL）**不生效**，故改用两个 partial unique index：
  - global：`name` 唯一（`WHERE scope='global'`，`sqlite_where`/`postgresql_where`）
  - personal：`(owner_id, name)` 唯一（`WHERE scope='personal'`）
  不同档之间互不影响（global 与 personal 允许同名，两个 personal 用户允许各自同名）。

### 5.2 彻底删除清单（Q5 解耦决定）

| 位置 | 删除内容 |
|---|---|
| `app/models/agent_skill.py` | 整个 `AgentSkill` 模型 |
| `app/models/__init__.py` | `AgentSkill` 导入与 `__all__` 条目 |
| `app/services/seed_service.py` | `BUILTIN_SKILLS` 常量及相关逻辑 |
| `app/services/skill_service.py` | `is_skill_enabled` / `list_skills` / `set_skill` 整文件 |
| `app/schemas/skill.py` | 旧 `SkillOut` / `SkillUpdate` |
| `app/api/projects.py:108-140` | `/projects/{id}/skills` GET + PUT 路由 |
| 迁移 | 新增 Alembic revision drop `agent_skills` 表 |

### 5.3 旧内置 skill 的重新定位（非删除，是改造）

| 旧 key | 新归宿 | 理由 |
|---|---|---|
| `rag_search` | **deepagents 内置 `@tool`** | agent 在 loop 中按需检索，取代 `orchestrator._retrieve_knowledge` 的预检索布尔守卫 |
| `rubric_review` / `consistency_check` / `quality_report` | 保留为独立审查服务 | 不进 skill 体系，走 `review_service` 现有路径 |
| `prior_art_hint` | 删除 | 占位，无运行时代码 |

---

## 6. 后端架构

### 6.1 新增模块切分

```
apps/api/app/skills/
├── __init__.py
├── storage.py          # MinIOStoreBackend(BaseStore): LangGraph BaseStore 适配 MinIO
├── loader.py           # 加载 skill：StoreBackend + SkillsMiddleware 集成
├── visibility.py       # 可见性合并：global ns ∪ personal ns（纯运行时）
├── validator.py        # SKILL.md frontmatter 校验（name 规则、description 长度）
└── service.py          # CRUD 业务逻辑（admin 全局 + 用户个人）

apps/api/app/sandbox/
├── __init__.py
└── docker_runner.py    # 自建 Docker sandbox：docker SDK 起隔离容器跑用户脚本
```

### 6.2 MinIO `BaseStore` 适配器（Q4/Q9）

`deepagents` 的 `StoreBackend` 包装 LangGraph 的 `BaseStore`（[StoreBackend 文档](https://reference.langchain.com/python/deepagents/backends/store/StoreBackend)）。实现 `MinIOStoreBackend(BaseStore)`，把 `put/get/search/delete` 映射到现有 `app/core/storage.py` 的 `MinioStorage`（复用已验证的 storage 抽象，不重复造轮子）。

MinIO 布局：`skills/<scope>/<owner_or_global>/<name>/{SKILL.md, scripts/, references/, assets/}`

### 6.3 deepagents agent 重写（Q8-B/Q10/Q16-A）

- `app/ai/agent.py`（新建）：`create_deep_agent(model=get_llm(...).bind_tools(...), skills=..., tools=[rag_search_tool])`。
- 取代 `app/ai/orchestrator.py` 的 `astream_generate`/`astream_chat`/`astream_rewrite` 一次性流，改为 agent loop。
- `rag_search` 从布尔守卫改造为 `@tool`，agent 在 loop 中按需调用。
- BYOK 降级（Q14-α）：agent 创建前检测模型 tool calling 支持，不支持 → 明确报错"当前模型不支持技能功能，请切换到支持 function calling 的模型"，**拒绝服务**。

### 6.4 Docker sandbox（Q12-b/Q15-A）

- `app/sandbox/docker_runner.py`：用 `docker` Python SDK 起隔离容器（受限镜像：无网络、只读 rootfs、CPU/内存上限、超时 kill），sandbox **直读 MinIO**（Q15-A：执行前从 MinIO 拉脚本到容器临时目录）。
- 注册为 deepagents 的脚本执行后端。
- 安全：容器 `network_mode="none"`、`read_only=True`（除 /tmp）、`mem_limit`/`cpus` 限制、超时 kill。

### 6.5 两套 CRUD API

- `app/api/skills.py`（用户域，`get_current_user`）：`/skills/mine`（个人 CRUD）、`/skills/visible`（global 只读 + personal）。
- `app/api/admin/skills.py`（admin 域，`require_admin`）：`/admin/skills`（全局 CRUD）。
- 在 `app/api/router.py` 和 `app/api/admin/__init__.py` 注册。
- 仿 `app/api/admin/content.py` 模式：inline 请求 `BaseModel` + 委托 service + 返回 `*Out`。

---

## 7. 前端架构

套用现有统一面板布局（顶栏导航，commit `adffa8d`）。

| 页面 | 路径 | 组件 | 说明 |
|---|---|---|---|
| admin 全局技能 | `app/(app)/admin/skills/page.tsx` | `<AdminSkillManager />` | 仿 `admin-template-manager.tsx`，全局 skill CRUD |
| 用户个人技能 | `app/(app)/settings/skills/page.tsx` | `<PersonalSkillManager />` | global 只读展示 + 个人 CRUD |

- 编辑器 v1 范围：表单式——`name`/`description` 输入框 + `SKILL.md` 正文大文本框 + `scripts/references/assets` 文件上传。文件树浏览器留 v2。
- 新增 `api.skills.*` 方法 + `useSkills`（admin）/`useMySkills`（user）hooks + `queryKeys.skills` 命名空间。
- SSE 消费扩展：新增 `tool_call`/`tool_result` 事件类型（复用现有 `request()` wrapper 模式）。
- 遵守 GOTCHAS F8（新 UI 组件**手写**，不用 shadcn CLI）。

---

## 8. 边界与降级

| 场景 | 处理 |
|---|---|
| 用户 BYOK 模型不支持 tool calling | **拒绝服务**（Q14-α），明确报错引导换模型 |
| MinIO 不可达 | skill CRUD 不可用，agent 降级为无 skill 的纯文本生成 |
| Docker daemon 不可用 | 脚本执行禁用，skill 的 `scripts/` 不可跑（`references/` 仍可读）|
| skill `status=draft` | 不进 runtime 可见集合 |
| skill 被删除 | MinIO 对象级联删除（`ondelete=CASCADE` + storage 层清理）|

---

## 9. 测试策略

- **后端**：沿用现有约定——SQLite 内存库 + `JSONB().with_variant(JSON, "sqlite")`（GOTCHAS G2）、函数式 `test_<subject>_<behavior>`、conftest `_FakeStorage`（MinIO 假实现）、`test@example.com`/`Pass1234!` 测试账号（GOTCHAS G4）。
- **deepagents 集成**：mock 模型层（不真实调 GLM），验证 skill 注入 + tool calling loop 结构。
- **Docker sandbox**：用 `subprocess` mock 或 `docker` SDK 的测试模式，不真实起容器。
- **前端**：组件快照 + 交互测试。

---

## 10. 实施改动清单（7 阶段，详见计划文档）

1. **Phase 1 数据层**：新 `Skill` 模型 + 迁移 + 删除旧 `agent_skills` 体系（含前端清理）。
2. **Phase 2 存储层**：MinIO `BaseStore` 适配器 + `StoreBackend` 集成。
3. **Phase 3 运行时**：deepagents agent 重写（含 `rag_search` 工具化）+ BYOK 降级护栏。
4. **Phase 4 sandbox**：自建 Docker sandbox + MinIO 脚本拉取。
5. **Phase 5 可见性 + CRUD**：合并服务 + admin/user 两套 API。
6. **Phase 6 前端**：admin 全局管理 + 用户个人管理页面。
7. **Phase 7 SSE + 收尾**：`tool_call`/`tool_result` 事件 + 全量验证。

---

## 11. grill 决策依据（为什么不是别的）

完整回溯见决定矩阵 §3「否决项」列。核心否决理由：

- **否决路线 A（prompt 注入）**：抛弃渐进式披露 = spec 残缺，skill 一多 token 爆，且无法实现脚本执行。
- **否决 E2B 自托管**：[e2b-dev/infra](https://github.com/e2b-dev/infra) 需 Kubernetes + Firecracker 微 VM 基础设施，对个人项目（单人开发）严重过度。
- **否决静默降级 (β)**：用户精心管理的 skill 在后台偷偷退化成"一段 prompt 文本"，渐进式披露和脚本执行全失效，用户还以为一切正常——隐性降级是产品事故温床。
- **否决发布流程 / public 档**：grill Q17-b 决定只有两档可见性，避免状态机复杂度（draft/active + personal/public + 审核 + 同名冲突）。
- **否决双轨（写交底书流不切 deepagents）**：两套 AI 调用路径维护成本翻倍，且 skill 不进主流程则建管理模块无意义。

---

## 12. 不在本契约范围

- skill 版本管理（v1 只存当前版本，历史版本留 v2）。
- skill 跨用户分享 / 导入导出。
- 移动端 UI。
- `org_admin` 多租户。
- skill 执行的资源计费 / 配额。

---

## 附：关键参考

- [Agent Skills specification](https://agentskills.io/specification)
- [Anthropic — Equipping Agents for the Real World](https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills)
- [deepagents StoreBackend](https://reference.langchain.com/python/deepagents/backends/store/StoreBackend)
- [deepagents SkillsMiddleware](https://reference.langchain.com/python/deepagents/middleware/skills)
- [deepagents Event streaming](https://docs.langchain.com/oss/python/deepagents/event-streaming)
- [GLM Coding Plan 概览](https://docs.bigmodel.cn/cn/coding-plan/overview)
- [GLM-4.6 Tool Calling 分析](https://cirra.ai/articles/glm-4-6-tool-calling-mcp-analysis)
