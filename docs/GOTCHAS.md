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
