# 天工 内部产品化补齐 — 设计

> 日期:2026-07-23
> 状态:已批准(方案 A 最小收口)
> 关联:`2026-07-13-tiangong-mvp-design.md` §8(角色与权限)、§11.4(部署)

## 1. 背景与定位

### 1.1 不是"迁移",是"补齐"

前期一度将本任务框定为"从 SaaS 迁移到内部产品",但代码探查否定了该前提:

- **无多租户耦合**:全代码库零 `tenant_id`;`User.org_id`(`models/user.py:23`)是预留死字段,`grep org_id` 在 `app/` 下零查询命中。
- **无组织/团队表**:唯一协作语义是项目级 `project_members`(`models/project_member.py`),不是组织级。
- **隔离靠 service 层**:`get_project`(`services/project_service.py:50`)等 `user_id != owner` 过滤,无 DB RLS。
- **无计费/订阅/套餐**:注册虽开放,但属于"未加限制"而非"SaaS 特征"。

结论:当前系统是**单实例多用户应用**,本质已接近内部工具形态。本任务不是架构迁移,而是**补齐内部产品尚缺的最后几块**。

### 1.2 目标形态(基于澄清)

| 维度 | 目标 |
|---|---|
| 使用规模 | 内部小团队(几人~十几人) |
| 数据隔离 | 按人隔离 + 可显式共享(现状即此,**不改**) |
| LLM 配置 | 保留 BYOK 全套(**不动**) |
| 账号发放 | 关闭开放注册;admin 可直接创建 + 可发邀请码(双轨) |
| 部署 | 全容器化,API+Web+PG+MinIO 同一 compose 一键起 |
| 访问 | 内网服务器,多人浏览器访问 |
| 保留 | 核心业务能力、分享链接、审计监控、`org_id` 预留字段 |
| 演进 | grant 白名单简化留作未来单列评估,本次不做 |

### 1.3 差距识别

逐项核对后,真实差距仅 3 项,且**完全正交、可独立交付**:

| 差距 | 性质 | 是否触碰业务逻辑 |
|---|---|---|
| ① 账号发放机制 | 核心新增 | 是(唯一触碰) |
| ② 全容器化 | 纯基建,新增文件 | 否 |
| ③ 内网部署配置化 | 配置层 | 否(只改环境变量,不改逻辑) |

无差距项(已具备,不动):按人隔离+共享、BYOK、核心业务能力、分享链接、审计监控、org 预留。

## 2. 差距 ①:账号发放机制

这是唯一有设计含量的部分,也是唯一触碰业务逻辑的改动。

### 2.1 关闭开放注册

**现状**:`apps/api/app/api/auth.py:34` `POST /register` 任何人可调,`auth_service.register_user` 无门槛。

**目标**:关闭开放入口,改为**邀请码门槛** + **admin 直建**双轨。注册端点**保留**但必须携带有效邀请码。

**设计决策:保留 `/register` 端点而非删除**。理由:
- 邀请码路径复用现有端点,前端注册页改造小(加一个邀请码字段)
- admin 直建走 admin 域独立端点,两条路径职责清晰
- 删除端点会让"邀请码注册"无处落脚,反而要新建端点

### 2.2 邀请码系统

**数据模型** — 新增 `InviteCode` 表:

```
invite_codes
├── id: UUID PK
├── code: str(8 位,大写字母+数字,去掉易混淆字符 0O1I),unique,索引
├── created_by_id: FK→users.id(admin 创建者)
├── max_uses: int(默认 1,可设多次用)
├── used_count: int(默认 0)
├── expires_at: datetime(nullable,默认 7 天后)
├── revoked_at: datetime(nullable)
└── created_at / updated_at
```

**为什么自建而非用现成库**:需求极简(生成/核销/吊销),一个表 + 几个方法即可,引入第三方依赖不划算,且与现有审计日志(`audit_logs`)衔接更直接。

**生成规则**:`secrets.choice` 从字母表 `ABCDEFGHJKLMNPQRSTUVWXYZ23456789`(32 字符,剔除 0O1I)取 8 位。碰撞概率:32^8 ≈ 1.1e12,加 unique 约束 + 重试即可。

**生命周期**:
- admin 在后台生成(可选 max_uses、有效期)
- 注册时核验:存在 + 未吊销 + 未过期 + `used_count < max_uses`
- 核销成功:事务内 `used_count += 1` + 创建用户
- admin 可吊销(`revoked_at`)

**审计**:邀请码生成/核销/吊销写 `audit_logs`,与现有 admin 操作审计一致(`services/admin_service.py` 模式)。

### 2.3 admin 直接创建用户

**现状**:`apps/api/app/api/admin/users.py` 只有列表/封禁/重置密码/授权,**无创建端点**。

**新增端点**:`POST /admin/users`,admin 域,`Depends(require_admin)`。
- 入参:username、email、password(初始)、role(默认 `user`)、可选 display_name
- 直接调用 `auth_service.register_user`(共享校验:EmailStr、username 唯一、密码强度),保证"所有写用户入口同一套校验"(GOTCHAS G4 教训)
- 创建后写审计
- **不需要邀请码**(admin 操作本身就是授权)

**关键设计:`register_user` 保持邀请码无关。** 邀请码核销逻辑放在 `/register` 端点的 API 层(先核销、再调 `register_user` 建用户),不侵入 service 函数签名。这样 admin 直建与邀请码注册两条路径都能干净地复用同一个 `register_user`,职责清晰。

### 2.4 注册流程变更

**后端**:`POST /register` 入参加 `invite_code: str`(必填)。**邀请码核销在 API 层**:端点先调 `invite_service.validate_and_consume(code)`(校验存在/未吊销/未过期/未用尽,并 `used_count += 1`),再调 `auth_service.register_user` 建用户,两者同一事务。`register_user` 本身不感知邀请码(见 §2.3 关键设计)。

**前端**:
- `components/auth-form.tsx` 注册模式增加"邀请码"输入框(必填)
- 登录模式不变
- 注册失败时区分错误:邀请码无效/已用尽/已过期 → 中文提示

### 2.5 admin 后台管理界面

**新增页面**:`apps/web/src/app/(app)/admin/invites/` — 邀请码管理。
- 列表:码、创建者、用量、有效期、状态(有效/已用尽/已吊销/已过期)
- 操作:生成(选 max_uses/有效期)、吊销、复制码
- 入口:加入 admin 顶栏导航(`components/navbar.tsx` admin 路径组)

**admin 用户管理页增强**:现有 `admin/users/` 页加"创建用户"按钮,打开对话框(复用 admin 创建端点)。

### 2.6 边界与约束

- **首个 admin 仍由命令行创建**(`scripts/create_admin.py`),不变。这是冷启动入口,与邀请码/admin 直建正交。
- **邀请码不与角色绑定**:注册即 `user` 角色,需 admin 角色只能 admin 直建。简化模型,避免"邀请码权限"复杂度。
- **不引入邮箱验证**:内部小团队,admin 发码即信任,不做邮件验证回路(YAGNI)。

## 3. 差距 ②:全容器化

纯基建,新增文件,不碰任何业务代码。

### 3.1 API 镜像

**新增** `apps/api/Dockerfile`:
- 基础镜像 `python:3.12-slim`
- 安装 `uv`(官方推荐方式)
- `uv sync --frozen --no-dev`(只装运行依赖)
- 启动:`uv run uvicorn app.main:app --host 0.0.0.0 --port 8000`
- 暴露 8000

### 3.2 Web 镜像

**新增** `apps/web/Dockerfile`:
- 多阶段构建
- `deps` 阶段:`node:20-alpine` + `pnpm install --frozen-lockfile`
- `builder` 阶段:`pnpm build`(需 `output: "standalone"`)
- `runner` 阶段:拷 `.next/standalone` + `.next/static` + `public`,精简运行镜像
- 暴露 3000

**改动** `apps/web/next.config.ts`:加 `output: "standalone"`(仅此一行)。

### 3.3 编排扩展

**改动** `docker-compose.yml`:在现有 postgres + minio 基础上增加 api、web 两个服务。
- `api`:build `./apps/api`,depends_on postgres(+ healthcheck)与 minio,环境变量从 `.env` 读,端口 8000
- `web`:build `./apps/web`,depends_on api,环境变量 `NEXT_PUBLIC_API_BASE_URL` 指向 api 服务,端口 3000
- 新增 `api` 与 `web` 服务的 healthcheck
- 数据层服务保持不变

**注意 compose 网络**:容器间用服务名访问(`postgres:5432`、`minio:9000`、`api:8000`)。`DATABASE_URL` 等需相应配置——这属于差距 ③。

## 4. 差距 ③:内网部署配置化

配置层改动,不改逻辑,只改环境变量与默认值。

### 4.1 关键发现:配置已基本就绪

探查发现 `apps/api/app/core/config.py` 的关键项**已经是环境变量驱动**:

- `cors_origins`(已有 CSV 解析 validator,`:37-43`)
- `cookie_domain`(默认 `localhost`,可覆盖)
- `cookie_secure`(默认 `False`,可覆盖)
- `minio_endpoint` / `minio_secure`

**结论:差距 ③ 几乎不需要改代码**,只需提供生产配置模板 + 文档。

### 4.2 交付物

**新增** `.env.production.example`:内网部署示例配置,标注每项含义。
```
# 数据库(容器间用服务名)
DATABASE_URL=postgresql+psycopg://tiangong:tiangong@postgres:5432/tiangong
# Cookie / CORS —— 改为内网域名
COOKIE_DOMAIN=intranet.yourcorp.local
COOKIE_SECURE=false  # 内网 HTTP,无 HTTPS;若加反代+HTTPS 则 true
CORS_ORIGINS=http://intranet.yourcorp.local
# MinIO(容器间)
MINIO_ENDPOINT=minio:9000
MINIO_SECURE=false
# 其余(JWT_SECRET、ENCRYPTION_KEY、GLM_API_KEY)从安全来源注入
```

**新增** `docs/deploy-internal.md`:内网部署步骤文档。
- 前置:内网服务器装 Docker
- 步骤:拷代码 → 填 `.env.production` → `docker compose --env-file .env.production up -d --build` → `docker compose exec api uv run alembic upgrade head` → 建首个 admin
- 验证:访问 `http://<内网域名>:3000`
- cookie domain / CORS 配置说明(GOTCHAS F4:跨 host cookie 传递)

### 4.3 边界:不做 HTTPS/反代

本次**不引入 nginx/caddy 反向代理与 HTTPS**。内网 HTTP 直接访问,`cookie_secure=false`。理由:
- 内网信任环境,HTTPS 收益有限
- 反代+证书是独立基建项,不应与"内部产品化"捆绑
- 留作后续:若需 HTTPS,加一层 caddy 自动证书即可,不影响应用代码

## 5. 改动清单与影响面

### 5.1 三块差距独立交付

```
差距① 账号发放   ←─ 触碰 auth/admin 域,新增 InviteCode 模型 + 迁移 + 端点 + 前端
差距② 容器化     ←─ 纯新增 Dockerfile + 改 compose + next.config 一行
差距③ 部署配置   ←─ 纯新增 .env 模板 + 文档,代码零改动
```

无依赖关系,可任意顺序实施、分开验收。推荐顺序:③(配置先行)→ ②(容器化)→ ①(账号发放),或并行。

### 5.2 文件级改动预估

| 差距 | 新增 | 修改 | 删除 |
|---|--- |---|---|
| ① 账号发放 | `models/invite_code.py`、迁移、`services/invite_service.py`、admin 端点、`admin/invites/` 前端页、auth-form 改造 | `auth.py`、`auth_service.py`、`admin/users.py`、`navbar.tsx`、`admin/users/` 页 | 无(注册端点保留) |
| ② 容器化 | `apps/api/Dockerfile`、`apps/web/Dockerfile` | `docker-compose.yml`、`apps/web/next.config.ts`(+1 行) | 无 |
| ③ 部署配置 | `.env.production.example`、`docs/deploy-internal.md` | 无 | 无 |

### 5.3 测试策略

- **差距①**:新增邀请码生成/核销/吊销单元测试;`/register` 携带邀请码的集成测试;admin 创建用户端点测试;**复用 GOTCHAS G4 教训——校验同一入口**。目标:测试数从 36 增至 ~45。
- **差距②**:容器化以"构建成功 + compose up 后 healthcheck 通过"为验收,不写单测。
- **差距③**:无测试(纯配置)。

### 5.4 风险与回滚

| 风险 | 缓解 |
|---|---|
| 关闭注册后冷启动 | 首个 admin 仍走 `create_admin.py`,与注册无关 |
| 邀请码迁移与现有数据冲突 | 新表,无冲突;回滚 = drop table + 还原 register 端点 |
| 容器化破坏现有开发流程 | Dockerfile 与本地 `uv run`/`pnpm dev` 并存,开发不受影响 |
| cookie domain 配错导致登录失效 | 部署文档明确标注(GOTCHAS F4),`.env.production.example` 给正确示例 |

## 6. 不做的事(YAGNI)

- 不删 `org_id`(保留预留)
- 不简化 grant 白名单(留作未来评估)
- 不引入组织/团队表
- 不做邮箱验证
- 不做 HTTPS/反向代理
- 不重塑前端 UI 为"团队工作台"叙事
- 不重写已验证的业务逻辑

## 7. 后续(plan 阶段)

本 spec 获批后,按三块差距拆为独立 plan(建议 3 份小 plan 而非 1 份大 plan,因其正交):
1. plan-③ 部署配置(最快,先行)
2. plan-② 容器化
3. plan-① 账号发放(工作量最大,最后)
