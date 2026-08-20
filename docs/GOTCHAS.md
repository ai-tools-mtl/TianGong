# 天工开发踩坑记录（Gotchas）

> 本文件记录实际开发中踩到的、**计划文档无法预见、只有跑起来才暴露**的坑。每条含：现象、根因、修复、预防。
> 新会话/新开发者开工前应通读本文件，避免重复踩坑。

---

## 后端（apps/api）

### G1: passlib 与 bcrypt 5.x 不兼容

- **现象**：`hash_password` 抛 `ValueError: password cannot be longer than 72 bytes`，且日志有 `AttributeError: module 'bcrypt' has no attribute '__about__'`
- **根因**：bcrypt 5.x 移除了 `__about__` 属性，passlib 1.7.4 未适配（passlib 已停止维护多年）
- **修复**：弃用 passlib，改用 bcrypt 库直接调用 `hashpw/checkpw`；密码做 72 字节截断
- **预防**：不要用停止维护的 passlib；直接用 bcrypt 库
- **影响任务**：计划 1 任务 1

### G2: JSONB 在 SQLite 测试库不可用

- **现象**：模型测试报 `Compiler can't render element of type JSONB`（SQLite 不支持 PostgreSQL 的 JSONB 类型）
- **根因**：计划用 SQLite 内存库做单元测试，但模型字段用了 PostgreSQL 专属的 JSONB
- **修复**：用 `JSONB().with_variant(JSON, "sqlite")`——生产用 JSONB（索引优化），测试降级为通用 JSON
- **预防**：任何 PostgreSQL 专属类型都要配 `.with_variant()` 兼容 SQLite 测试库
- **影响任务**：计划 1 任务 2

### G3: JWT sub 是字符串，查 UUID 列报错

- **现象**：`/auth/me` 接口报 `AttributeError: 'str' object has no attribute 'hex'`
- **根因**：JWT payload 里 `sub` 存的是 `str(user.id)`，但 `get_current_user` 用字符串直接查 `User.id`（UUID 列），SQLAlchemy 的 Uuid 类型处理器期望 UUID 对象
- **修复**：`deps.py` 里查询前用 `uuid.UUID(user_id)` 转换，并 `try/except ValueError` 防非法 UUID
- **预防**：JWT 里存的是字符串，查 UUID 列前必须显式转换
- **影响任务**：计划 1 任务 5

### G4: 管理员邮箱校验绕过（能创建却登不进）⚠️ 重要

- **现象**：用 `create_admin` 脚本创建的 `admin@tiangong.local` 账号，登录时后端报 `value is not a valid email address: The part after the @-sign is a special-use or reserved name`
- **根因**：`create_admin` 脚本直接写库，**绕过了 EmailStr 校验**；而 `.local` 是 RFC 6761 保留顶级域名，Pydantic EmailStr（基于 email-validator）拒绝它。导致"能创建的账号却无法登录"
- **修复**：
  1. 脚本创建前用 `email_validator.validate_email(email, check_deliverability=False)` 校验
  2. 非法邮箱直接报错退出
  3. 现有管理员邮箱改为合法域名（`admin@tiangong.dev`）
- **预防**：
  - **所有写用户的入口（注册 API、脚本、未来批量导入）必须用同一套邮箱校验**，不能绕过
  - `.local`/`.localhost`/`.test`/`.example` 等都是保留域名，测试账号别用，用 `.dev`/`.com`/`.test.com` 这类
  - 测试用户用 `xxx@test.com` / `xxx@example.com` 这类 email-validator 接受的
- **影响任务**：计划 1 任务 8 + 登录验证

### G5: pgvector 扩展在新库未创建，迁移必报 "type vector does not exist" ⚠️

- **现象**：新库（`docker compose down -v` 后重起）跑 `alembic upgrade head`，到第 5 个迁移 `ee50036c9e86_add_knowledge_chunks_with_pgvector` 报 `psycopg.errors.UndefinedObject: type "vector" does not exist`，前 4 个迁移被 PostgreSQL 事务性 DDL 整体回滚，库里一张表都没留下
- **根因**：迁移文件用 `pgvector.sqlalchemy.VECTOR(dim=2048)` 定义 `embedding` 列，但**整个迁移没有 `CREATE EXTENSION vector`**。`pgvector/pgvector:pg16` 镜像只提供扩展二进制，扩展不会自动安装到数据库——必须显式 `CREATE EXTENSION`。迁移作者默认扩展已存在，新库初始化必踩
- **修复**：在 `ee50036c9e86` 的 `upgrade()` 开头加 `op.execute('CREATE EXTENSION IF NOT EXISTS vector')`（`IF NOT EXISTS` 保证已装环境幂等）；`downgrade()` 不删扩展，避免误伤其他用途。配合 `scripts/init_db.py` 一条命令完成初始化
- **预防**：
  - 任何迁移用到 PostgreSQL 扩展专属类型（pgvector / PostGIS / pg_trgm 等），**迁移自身必须负责 `CREATE EXTENSION IF NOT EXISTS`**，不能假定扩展已存在
  - `pgvector/pgvector` 镜像 ≠ 扩展已启用，两者是两回事
  - 用 `scripts/init_db.py`（而非手动一条条敲）做初始化，扩展依赖已在迁移内闭环
- **影响任务**：计划 6（知识库 RAG，建 knowledge_chunks 表）+ 全员本地初始化

### G6: SessionLocal expire_on_commit=False —— commit 后读 server-default 列必须显式 refresh ⚠️

- **现象**：某次把 `SessionLocal` 从默认 `expire_on_commit=True` 改为 `False`（C1 修复）后，新写的「commit 后读 ORM 属性」代码读到的 `created_at`/`updated_at` 是 None（PG 上表现为 API 返回空时间戳），而不是 DB 生成的真实值
- **根因**：`expire_on_commit=False` 意味着 commit 后 ORM 对象**不再自动 expire**，属性访问不再触发 lazy reload。对于 `created_at`/`updated_at`（`TimestampMixin` 里 `server_default=func.now()`，由 DB 端赋值）这类列，Python 端 INSERT 时根本没有该值——commit 后不 reload 就永远是 None。客户端生成的 UUID 主键（`default=uuid.uuid4`）则无此问题（flush 时已在 Python 端赋值）
- **修复**：`SessionLocal` 设 `expire_on_commit=False`（C1 修复，根治 commit 后冗余 lazy load）；**同时**任何「commit 后要读 server-default 列」的地方补 `db.refresh(obj)`。全项目审计后只有 `memories.py:56/71` 两处需要补
- **预防**（编码规范）：
  - **commit 后读 server-default 列（时间戳 / 自增 ID / DB 端 default）→ 必须先 `db.refresh(obj)`**
  - commit 后读客户端 UUID 主键或 Python 端赋值的字段（status/scope 等）→ 无需 refresh，直接读
  - 新增 create/update service 时，遵循主流 `commit(); refresh(obj)` 模式（项目里已有 44 处这么写）
  - 配置守卫测试：`tests/test_sessionlocal_config.py::test_sessionlocal_expire_on_commit_is_false`
- **影响**：C1 技术债修复（`fix/c1-expire-on-commit` 分支），见 [2026-07-29-c1-expire-on-commit-design.md](superpowers/specs/2026-07-29-c1-expire-on-commit-design.md)

### G7: 上下文压缩的四处隐性约定（compress_history / JSONType / deepagents 中间件 / 日志出口）⚠️

- **现象**：接入对话上下文压缩（`app/ai/context_compactor.py`）时踩到四个计划文档没写清、只有跑起来/读源码才暴露的点。
- **根因 + 修复**：
  1. **`JSONType` 是实例不是类，迁移里不能加 `()`**。`JSONType = JSONB().with_variant(JSON, "sqlite")`（`base.py:9`）返回的是 JSONB **实例**（`with_variant` 的返回值）。Alembic autogenerate 可能产出 `postgresql.JSONB(...).with_variant(sa.JSON(), 'sqlite')`（可用）或误导你写 `JSONType()`（**抛 `TypeError: 'JSONB' object is not callable`**）。**正确**：迁移列用 `sa.Column('context_meta', JSONType, nullable=True)`——裸 `JSONType`，无括号（与 `audit_log.py`、`mcp_server.py` 既有写法一致）。
  2. **`compress_history` 的返回契约分三种路径，`current_input` 不一定在末尾**。未触发路径只返回历史 dict（**不含** `current_input`）；触发/降级路径才在末尾 append 了 `current_input`。接入方（`orchestrator.astream_chat`、`init_orchestrator._build_*`）必须 `if not snapshot.triggered: messages.append(current_input)` 补一次，否则**短对话会静默丢失用户当前输入**。
  3. **deepagents 无 per-call 排除中间件的参数**。`create_deep_agent(...)` 的签名只有 `middleware=`（追加），**没有** `excluded_middleware`。唯一排除路径是 beta 级、进程全局的 `register_harness_profile(key, HarnessProfile(excluded_middleware={...}))`，副作用大。**采纳的方案**：不排除库默认 `SummarizationMiddleware`，靠天工 `compress_history` 先预处理（产出更短历史），库中间件的 ~170k-token 阈值几乎不会再触发，作为 rarely-firing 兜底——V1 接受。V2 若要完全可控再用全局注册。
  4. **打日志必须用 `loguru`，不能用标准 `logging`** ⚠️**最隐蔽**。项目用 `loguru`（`main.py: import loguru`，`storage.py/archiver.py: from loguru import logger`），**没有**任何 `logging.basicConfig`/`dictConfig`，也没给标准 logging 装 `InterceptHandler`。后果：root logger 默认 WARNING + 无 handler，**`logging.getLogger(__name__).info(...)` 全部被静默丢弃**——代码里有日志语句但永远不输出，极易误以为"已埋点"实则黑盒。**正确**：一律 `from loguru import logger; logger.info(...)`（loguru 默认 DEBUG 级，必输出）。压缩模块起初误用标准 `logging` 导致 4 处触发日志全部静默，后改为 loguru 才生效。
- **预防**：新写迁移用项目 `JSONType` 时裸用不加 `()`；接入 `compress_history` 务必处理未触发路径的 `current_input`；不要假设 deepagents 支持 per-call 中间件排除；**打日志一律用 `loguru.logger`，禁用标准 `logging`**。
- **影响任务**：计划「对话上下文压缩」任务 6/7/8/9，见 [2026-07-30-context-compression-design.md](superpowers/specs/2026-07-30-context-compression-design.md)

---

## 前端（apps/web）

### F1: shadcn/ui 4.x 不稳定

- **现象**：`npx shadcn@latest init` 装了 base-nova 模板（基于 @base-ui/react），但 `add` 组件时不生成 `src/components/ui/` 文件，静默失败
- **根因**：shadcn 4.x（2026 中）刚发布，base-nova 风格的行为与文档不符，CLI 不稳定
- **修复**：退回 shadcn **3.x**（基于 Radix，成熟稳定，文档完善），`npx shadcn@3.2.0 init/add`
- **预防**：前端工具链尽量用稳定版，不追最新大版本；shadcn 锁 3.x
- **影响任务**：计划 2 任务 0

### F2: pnpm install 网络超时

- **现象**：`pnpm install` 报 `TimeoutError: The operation was aborted due to timeout`
- **根因**：pnpm 默认 fetch-timeout 较短，国内网络拉 npm 包易超时
- **修复**：`pnpm config set fetch-timeout 600000 && pnpm config set fetch-retries 5`；必要时加 `--registry https://registry.npmmirror.com`
- **预防**：新机器首次装依赖前先调超时配置
- **影响任务**：计划 2 任务 0

### F3: TanStack Query data 类型推断为 any

- **现象**：`pnpm build` 报 `Parameter 'p' implicitly has an 'any' type`（projects.map 的回调参数）
- **根因**：`useQuery({ queryFn: api.listProjects })` 没有显式泛型，data 推断为 `unknown`，解构后访问 `.map` 触发隐式 any
- **修复**：`useQuery<Project[]>({...})` 显式标注返回类型；解构处 `const projects = data ?? []` 兜底 undefined
- **预防**：所有 useQuery 都加显式泛型 `useQuery<T[]>(...)`，别依赖推断
- **影响任务**：计划 2 任务 1/5

**变种（refactor/admin-ia-phase2 踩到）**：即便 hook 写了泛型 `useQuery<AuditLogPage>`，下面这种写法 map 参数仍然 any：
```ts
const items = auditData?.items ?? []   // ❌ TS 推不出 AuditLogItem[]
items.map((a) => ...)                  //    a: any
```
**根因**：`?? []` 里的空数组字面量是 `never[]`，与 `AuditLogItem[] | undefined` 联合后退化为 `any[]`。同理 `stats.by_model.map((m) => ...)` 也会触发。
**修复二选一**：
1. 给解构变量显式标注：`const items: AuditLogItem[] = auditData?.items ?? []`
2. 给 map 回调参数显式标注：`stats.by_model.map((m: LLMStatsByModel) => ...)`

推荐方式 2（更局部、不影响其它使用点）。

### F4: httpOnly cookie 跨 host 不传递（TestClient / curl）

- **现象**：登录成功（200）但后续请求 cookie 没带上，返回 401
- **根因**：后端设 cookie 时带了 `domain=localhost`，但请求用 `127.0.0.1`，domain 不匹配 → 浏览器/curl/TestClient 拒收 cookie
- **修复**：后端 `_set_auth_cookies` 改为 `domain` 为空时不传该参数；测试用 `monkeypatch` 清空 cookie_domain
- **预防**：开发/测试时统一用 `localhost`（前后端都别用 `127.0.0.1`）；cookie domain 配置留空则不限制
- **影响任务**：计划 1 任务 5（后端）+ 计划 2 E2E（前端）

### F5: Turbopack `@plugin` 解析 npm 包名失败 ⚠️

- **现象**：`globals.css` 里 `@plugin "@tailwindcss/typography"`，`pnpm dev`（Turbopack）报 `Can't resolve '@tailwindcss/typography' in '.../src/app'`；但 `pnpm build` 不报错（两者的 CSS 解析路径不同）
- **根因**：Turbopack 的 CSS `@plugin` 指令解析器在 **Windows + pnpm symlink** 环境下解析 npm 包名失败，不如 JS `import` 解析成熟。包明明装好了（`require.resolve` 成功）但 `@plugin` 找不到
- **修复**：卸载 `@tailwindcss/typography`，手写约 50 行 `.prose` CSS 直接设 h1-h6/p/ul/ol/blockquote/code/pre/table 的颜色与间距，全部走项目 token
- **预防**：Tailwind v4 在 Turbopack 下**慎用 `@plugin` 引 npm 包**；能用 CSS 手写就手写，少一个依赖链路上的解析风险
- **影响任务**：计划 8 阶段 0

### F6: next-themes 装了但没接 ThemeProvider

- **现象**：暗色主题完全无效，`useTheme()` 在组件里返回默认值；`sonner.tsx` 调了 `useTheme()` 但 toggle 不起作用
- **根因**：`next-themes` 已在 dependencies 里，`sonner.tsx` 也 import 了 `useTheme`，但全局**没有 `<ThemeProvider>` 包裹**——`useTheme` 脱离 provider 就是空转
- **修复**：`providers.tsx` 包一层 `<ThemeProvider attribute="class" defaultTheme="light" enableSystem disableTransitionOnChange>`；`<html>` 加 `suppressHydrationWarning`
- **预防**：装了 next-themes 必须在根部接 provider；class 策略下 `<html>` 必须加 `suppressHydrationWarning` 防 SSR 水合警告
- **影响任务**：计划 8 阶段 0

### F7: 组件放进 grid 时的双重宽度声明

- **现象**：改 grid 列宽（如 `grid-cols-[...320px]`）时，AI 面板宽度不跟随，布局错位
- **根因**：`ai-chat-panel.tsx` 既被父 grid 列（`320px`）约束，自身又带 `style={{ width: 320 }}` + `border-l pl-4`——宽度声明在两处，互相覆盖
- **修复**：删组件内联 style 和自带 border，宽度完全交给 grid 列；border 交给 grid 间隔处理
- **预防**：组件放进 grid 时，**宽度声明只能在一处**——要么 grid 列模板、要么组件自身，不能两边都写
- **影响任务**：计划 8 阶段 2

### F8: shadcn CLI 与 MCP SDK 冲突，无法 `add` 组件 ⚠️

- **现象**：`pnpm dlx shadcn@latest add skeleton`（或 table/select/switch 等）直接报错退出：
  ```
  Error [ERR_PACKAGE_PATH_NOT_EXPORTED]: Package subpath './v3' is not defined by "exports"
  in .../@modelcontextprotocol/sdk/.../node_modules/zod/package.json imported from
  .../@modelcontextprotocol/sdk/.../dist/esm/server/zod-compat.js
  ```
- **根因**：项目装了 `@modelcontextprotocol/sdk`（MCP server 用），它对 `zod` 子路径 `./v3` 的 import 与 shadcn CLI 内部用的 zod 版本不兼容。shadcn CLI 启动时加载 MCP SDK 触发 zod 解析失败，整个 CLI 直接挂掉，连 `add` 子命令都进不去。
- **修复**：**手写 shadcn 等价件**。shadcn 大部分组件（skeleton / table / etc.）就是纯 className 封装，去 [ui.shadcn.com/docs](https://ui.shadcn.com/docs/components/) 复制对应组件源码到 `apps/web/src/components/ui/<name>.tsx`，改 import 路径即可（保持 API 一致，未来修好 CLI 能无缝替换）。
  - 已手写的：`skeleton.tsx`（refactor/admin-ia-phase1）、`table.tsx`（refactor/admin-ia-phase2 切片 1）
- **预防**：不要在装了 MCP SDK 的项目里直接跑 `shadcn add`；遇到要装的组件先查官方源码，能手写就手写（5-100 行），别耗在 CLI 上
- **影响任务**：refactor/admin-ia-phase1（skeleton）+ phase2 切片 1（table）

---

## 通用 / 环境

### E1: Windows curl 中文 body 编码错误

- **现象**：curl 传中文 JSON body 报 `There was an error parsing the body`
- **根因**：Windows Git Bash 的 curl 默认 GBK 编码，中文 UTF-8 内容被破坏
- **修复**：E2E 验证用英文数据；或用 `-d @file.json` 从文件读（文件存为 UTF-8）
- **预防**：Windows 下 curl 测中文用文件方式，别直接内联
- **影响任务**：计划 1/2 端到端验证

### E2: uv.lock 与 pnpm-lock.yaml 必须提交

- **现象**：（非 bug，是规范）依赖锁文件不提交会导致不同环境装出不同版本
- **修复**：`uv.lock`（后端）、`pnpm-lock.yaml`（前端）都纳入版本控制
- **预防**：每次 `add` 依赖后，lock 文件要一起 commit
- **影响任务**：计划 1/2

### E3: LlamaIndex OpenAIEmbedding 不支持非 OpenAI 官方模型名 ⚠️

- **现象**：`OpenAIEmbedding(model='embedding-3', api_base='智谱...')` 报 `ValueError: 'embedding-3' is not a valid OpenAIEmbeddingModelType`
- **根因**：LlamaIndex 的 `OpenAIEmbedding` 在构造时强制用 `OpenAIEmbeddingModelType` 枚举验证模型名，只接受 OpenAI 官方模型（text-embedding-ada-002 等），无法接入智谱/DeepSeek 等国产模型的 embedding
- **修复**：弃用 LlamaIndex 做 embedding，改用 **LangChain 的 `OpenAIEmbeddings`**（接受任意模型名 + 自定义 base_url）。向量存储直接用 pgvector（SQLAlchemy 操作）。设计文档原定 LlamaIndex，据此调整为 LangChain + pgvector
- **预防**：国产模型生态优先用 LangChain（更灵活），LlamaIndex 对非 OpenAI 模型支持差
- **影响任务**：计划 6（知识库 RAG）

### E4: Windows 测试环境必须先起 docker 服务，否则 app startup 像挂死 ⚠️

- **现象**：`uv run pytest` 任何用到 `client` fixture 的测试卡住数分钟无输出（CPU 几乎为 0），像死锁
- **根因**：main.py 的 startup（恢复扫描/内置技能同步/checkpointer 初始化）直连真实 `SessionLocal`（PG）与 MinIO。docker 没起时每个连接走 urllib3 重试 ~30s，多步叠加把 startup 拖成数分钟；`TIANGONG_TESTING=1` 只跳过 embedding/rerank/firecrawl 探活，跳不过这些
- **修复**：跑测试前先 `docker compose up -d postgres minio`（或干脆起全套）。Docker Desktop 没开时先启动它再等 engine ready
- **预防**：Windows 本机跑全量测试前确认 `docker ps` 里 postgres/minio 是 healthy
- **影响任务**：feat/langgraph-resume-hitl-store（定位此问题耗了一次完整调试）

### E5: SQLAlchemy `Uuid` 列绑定必须传 UUID 对象，传 str 直接 AttributeError

- **现象**：对 UUID 主键列查询/写入时报 `'str' object has no attribute 'hex'`（sqltypes.py 的 bind processor）
- **根因**：SQLAlchemy 2.0 的 `Uuid` 类型在 native_uuid 路径下要求绑定值是 `uuid.UUID`；**sqlite 测试兼容表用 String(36) 掩盖了这一点**，同样的代码 sqlite 过、PG 语义下炸
- **修复**：跨边界拿到的字符串 id 一律先 `uuid.UUID(s)` 转换再进 ORM（见 `app/ai/store.py` 的 `_as_uuid`）
- **预防**：写 Store/adapter 层这种接受外部字符串 key 的代码时，入口处统一转 UUID
- **影响任务**：feat/langgraph-resume-hitl-store（CompositeAgentStore）

### E6: 两个存量迁移 bug 在真实数据上必炸（已修）⚠️

- **现象**：开发库 `alembic upgrade head` 失败：① `JSONB(astext_text=)` TypeError（笔误，正确是 `astext_type`）；② init 去重迁移把孤儿会话 `project_id` 指向哨兵 UUID，触发 `ForeignKeyViolation`
- **根因**：① 是拼写错误，该迁移在任何环境都跑不过（此前从未有库走到它）；② 写迁移时忽略了 project_id 的 FK 约束，无脏数据的库恰好不受影响
- **修复**：commit 73926f9 —— ① 改 `astext_type`；② 改为把多余会话 `kind='init_dup'`（避开部分索引条件，不碰外键、不删数据）
- **预防**：迁移文件要在一个**有历史脏数据的真实库**上验证过才算数；写「哨兵值」前先查目标列的约束
- **影响任务**：feat/support-access（本机 PG 实测通过到 head）

### E7: langgraph「有 checkpointer 必须有 thread_id」入口级 ValueError ⚠️（已修）

**坑**：langgraph 的 `pregel/main.py:2589` 有入口级检查——图带 checkpointer 且
config 无任何 `configurable` key 时，`astream_events` **无条件抛**
`ValueError: Checkpointer requires one or more of the following 'configurable' keys: thread_id, checkpoint_ns, checkpoint_id`。
与是否触发 interrupt 无关。

**后果**：orchestrator 三路 `build_agent` 均传 `get_checkpointer()`，而 generate 端点
是唯一不传 thread_id 的 agent loop 路径（`_astream_agent_events` 里 config=None）——
**generate（AI 生成草稿）自 2026-08-13 checkpoint 合并起在 PG 环境（checkpointer
初始化成功）下每次调用都以 llm_error 告终**。chat/resume 传 thread_id 幸免。单测
未暴露：test_orchestrator 全 mock build_agent，走不到 langgraph 入口检查。

**修复**（T2 批1，2026-08-17）：generate 去 checkpointer（它无 message、无 resume
能力，checkpoint 零收益纯隐患）；revise 从设计上就不传。探针测试
`test_langgraph_probe.py` 四条钉死行为，升级 langgraph 时的回归警报。

**顺带观察**：`astream_events(version="v2")` 对原生 StateGraph 的 interrupt **不
emit `on_interrupt` 事件**（只出现在 `astream(stream_mode='updates')` 的
`__interrupt__` 块）；生产 orchestrator 的 on_interrupt 监听在 deepagents
middleware 路径有效（HITL 卡片已验证）——两套图的事件形态不同，勿用最小图推断
deepagents 行为。

### E8: 两个 pytest 进程并发跑会互相污染（共享 docker PG）⚠️

**坑**：同时起两个 pytest（如全量 + 单文件调试），TestClient startup 与测试数据
写的是**同一个 docker postgres 库**——两进程并发写同名表/唯一键互踩，产生大片
与代码无关的 flaky 失败。实测：串行重放（--lf）141 个失败里 113 个是并发污染，
真实失败仅 28 个。

**规矩**：跑全量期间**不要**并行起任何 pytest/uvicorn（连测试库的都算）；需要
调试时等全量跑完，或用 --lf 按失败清单分组验证。判定基线失败时，串行复跑是
唯一可信手段。

### E9: Windows 直接 `uvicorn app.main:app` 起 dev server，psycopg 异步池连不上库 ⚠️

**坑**：Windows 默认事件循环策略是 ProactorEventLoop，psycopg3 async 不支持。
直接 `uv run uvicorn app.main:app` 起来后日志反复刷
`error connecting in 'pool-1': Psycopg cannot use the 'ProactorEventLoop' to run in async mode`。

**关键事实（2026-08-19 修正）**：uvicorn 在 win32 上 `--reload` 或 `--workers >1`
时（`Config.use_subprocess=True`）实际用 **SelectorEventLoop**，psycopg 异步完全
可用——开发常态 `uvicorn --reload` 不踩此坑；只有单进程裸跑才落到 Proactor。

**代码内已修（checkpoint.py，2026-08-19）**：`init_checkpointer` 对 win32 +
ProactorEventLoop 提前探测、立即 fail-open 降级（warning 给出可行动原因），
不再 30s 空等 + 后台无限重试刷屏。同日修复的三层叠加 bug（症状是
`missing "=" after "postgresql+psycopg://..."` 刷屏 + Checkpointer 永远降级）：

1. **方言 URL 直喂 psycopg**：`postgresql+psycopg://` 是 SQLAlchemy 方言前缀，
   psycopg 只认 `postgresql://`，须剥 `+driver` 后缀再传 `AsyncConnectionPool`；
2. **pool 连接参数缺失**：须对齐官方 `from_conn_string` 的
   `autocommit=True`（setup() 迁移含 `CREATE INDEX CONCURRENTLY`，不能在事务块内）
   + `dict_row`（saver 查询按列名取值）+ `prepare_threshold=0`；
3. **失败不关池**：fail-open 降级时必须 `await pool.close()`，否则 pool 后台
   worker 持失败配置无限重试，WARNING 永续刷屏。另补 `close_checkpointer()`
   挂到 app shutdown，否则 pool 挂活连接拖住优雅停机/脚本收尾。

要完整持久化（checkpointer 生效）就带 `--reload` 跑；裸跑会优雅降级无持久化
（resume/HITL 随之 fail-open）。`POST /api/v1/auth/login` 返回 200 即链路已通。

### E10: 测试里 `get_settings.cache_clear()` 造成 settings 双实例精神分裂 ⚠️（已修）

**坑**：`app.main` 等模块在**导入期**捕获 `settings = get_settings()`（实例 A）。
任何测试调 `get_settings.cache_clear()` 后，后续 `get_settings()` 返回**新实例 B**——
conftest 的 `_clear_cookie_domain`（autouse，monkeypatch 补丁 cookie_domain=""）
打到 B 上，而 auth 读 A（cookie_domain 还是 'localhost'）→ Set-Cookie 带
`Domain=localhost` → httpx 对 `http://testserver` 拒收该 cookie → **该文件之后
（按收集序）所有 client 测试批量 401**。2026-08-19 实测 103 个失败横跨 22 个
文件，单文件/小组重跑全绿，极具迷惑性。

**触发条件微妙**：污染源是 `test_logging_security_config.py`，但只有**此前已有
任何 client 测试**（先导入了 app.main、绑定了 A）才发作——单跑该文件不污染，
与 `test_llm_token_logging.py`（或任意更早的 client 文件）组合必污染。

**定位手法**：金丝雀二分（用 `test_terms_api.py` 做金丝雀，按收集序二分前缀文件），
再写一次性探针测试打印 Set-Cookie 头 + `get_settings()` 与 `main.settings` 的
`id()`——两者不同即坐实分叉。

**修复**：该文件加 autouse fixture 把 `config_mod.get_settings` 整体替换成
**替身**（`cache_clear` 空操作、每次调 `Settings.from_env()` 现建），真 lru_cache
原封不动（3.14 起 `_lru_cache_wrapper` 无 `.cache` 内部字典可快照，故整函数换身）。
`test_rag_config.py` 头注释早已记录同款坑（彼时选择直接不用 cache_clear）。

**规矩**：测试里**永远别 `get_settings.cache_clear()`**。要按 env 验证 Settings
validator，直接调 `Settings.from_env()`，或像本次一样模块属性换身。

### E11: PG 专属部分唯一索引在 SQLite 测试库是盲区，「新对话」线上 500 ⚠️（已修）

**坑**：t0p1u2v3w4x5（P0-1）加的部分唯一索引 `uq_conversations_init_one_unlanded`
（同一 user 的未落地 init 会话最多 1 条）与 ChatGPT 式多会话设计直接冲突——
用户已有一个未落地会话时点「+ 新对话」，INSERT 第二条必撞约束 →
IntegrityError → 500（2026-08-19 线上报障）。而该索引**只存在于迁移**
（模型层无定义；测试库走 `Base.metadata` 建表，从不跑 PG 专属迁移），所以
`test_create_and_list_conversations`（连建两个会话）在 SQLite 上一直是绿的——
**测试绿 ≠ 生产绿**，PG 专属约束的测试盲区。

**坑中坑**：删索引迁移内部步骤顺序敏感——若先恢复 init_dup 数据再 drop 索引，
恢复动作当场撞这个索引（同一 user 出现第二条未落地 init 会话）；必须
**先 drop 索引、再 UPDATE 恢复数据**（同事务 DDL 顺序敏感，写反即回滚）。

**修复**（z1a2b3c4d5e6）：drop 索引 + 恢复当年被旧迁移改 `kind='init_dup'`
「牺牲」的真实会话；防双击重复落地收敛到行锁单防线——`create_project` 加
`commit=False` 参数，落地路径「建项目 + 写 project_id 标记」同一事务提交，
FOR UPDATE 持锁到 commit 完成。原先 create_project 自管 commit 会中途释放
行锁（窗口期内并发请求可钻入），这才是当初需要索引兜底的根因——事务收紧后
兜底不再必要。

**规矩**：给生产加 DB 层约束前先问「SQLite 测试库能否等价建出」；PG 专属
约束（部分索引、CONCURRENTLY 等）必须补 PG 环境验证或迁移内自测，不能只靠
SQLite 测试套件背书。


### E12: with_structured_output 对国产 provider 是「双形态失败」，且静默吞异常会把故障伪装成成功 ⚠️（已修）

**坑**（2026-08-19 dogfood，交底书审查「全 50 分评分失败」事故）：langchain
`with_structured_output` 走 OpenAI `response_format`（json_schema），国产
provider 不支持时有**两种失败形态**：

1. **本地失败**：langchain 链不支持 → `NotImplementedError`/`AttributeError`；
2. **远端失败**：链构造成功，服务端 API 返回 400 拒绝 response_format——
   DeepSeek 实测报 `This response_format type is unavailable now`
   （**普通 invoke 完全正常**，只有结构化通道挂）。

旧 `_score_dimension` 只把形态 1 路由到文本 fallback，形态 2 穿透后又被外层
`except Exception: return (50, "评分失败", "请重试")` 静默吞掉——于是 LLM
每次调用都失败，审查却「成功」落库一份全 50 分废报告，前端 toast「审查完成」，
真实错误（400）在服务端日志里一个字都没有。**吞异常 + 无日志 = 故障伪装成
成功，比直接报错恶劣得多**。

**修复**：

1. fallback 触发条件扩为 `(NotImplementedError, AttributeError, BadRequestError)`
   （`_score_dimension` 与 `_check_cross_section_consistency` 两处同策略）；
2. 删除静默兜底：单 run 失败 → `logger.warning` + 该 run 兜底 50 分；**全部
   run 失败 → 拒绝落库**，`raise ValidationError(friendly_llm_error(last_exc))`
   把真实原因（余额不足/key 失效/response_format 不支持…）透给前端；
3. 前端审查页 `onError` 展示后端 message（不再写死「审查失败」）。

**规矩**：用 `with_structured_output` 的 provider 兼容判断不能只捕本地异常，
`openai.BadRequestError`（服务端拒绝 response_format）是同等信号；任何 LLM
调用点的 `except Exception` 兜底必须打日志，且「全部调用失败」绝不能伪装成
成功出报告——宁可报错，不出废数据。

**续坑（同日）**：文本 fallback 路径没有 Pydantic 校验，LLM 漏输出字段时
dict 直接落库——实测 DeepSeek 只给 `location_section_keys` 不给
`location_sections`，前端 `issue.location_sections.length` 当场 TypeError
崩页。修法：`_postprocess` 单点规范化按 schema 补齐五字段缺省（D14 精神，
前端不做二次防御）；前端 `?? []` 兜存量脏数据。教训：**结构化输出 schema
同时是数据契约——fallback 路径产出必须过同一套字段规范化**。


### E13: Windows 裸机 weasyprint 缺 GTK runtime，PDF 导出 500 ⚠️（已修为友好 503）

**坑**（2026-08-19 dogfood，审查报告导出）：weasyprint 经 cffi 动态加载
GTK/Pango 系统库（libgobject-2.0-0 等），Windows 裸机没装 → `OSError:
cannot load library 'libgobject-2.0-0': error 0x7e` → 导出端点裸 500。
**生产 Docker 不受影响**（Dockerfile 已装 libpango + Noto CJK 中文字体），
此错只在无 GTK 的裸机/开发机出现；pdf_service（交底书导出）同一依赖，
同环境同样不可用。winget 无现成 GTK runtime 包。

**修复**：`review_export_service` 捕获 weasyprint 的 OSError →
`ServiceUnavailableError`（503 + 中文指引，drawio 同款 fail-closed）+
logger.error；前端导出从 `<a>` 直开改 fetch+blob，503 时 toast 友好文案
（`<a>` 直开 503 只能看见一页 JSON）。

**规矩**：可选系统依赖的报错要「可诊断、可行动」——明确告诉用户缺什么、
哪类环境会缺、怎么补，而不是让 traceback 直接怼脸。

**本地开发补依赖**（需要真正导 PDF 时）：装 GTK runtime
（如 <https://github.com/tschoonj/GTK-for-Windows-Runtime-Environment-Installer>）
后重启后端；或只在 Docker 环境验证 PDF 功能。


