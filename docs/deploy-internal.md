# 天工 内网部署指南

> 面向场景:内网服务器部署,团队多人浏览器访问。
> 配套:仓库根 `.env.production.example`。

## 前置条件

内网服务器( Linux / Windows 均可)需安装:

- **Docker Engine** + **Docker Compose v2**(随 Docker Desktop 或独立安装)
- 验证:`docker compose version` 能输出版本号

无需在服务器上装 Python / Node / pnpm —— 全部跑在容器里。

另需按 README「预下载本地模型」把模型下载到仓库 `models/` 目录:embedding 的 `bge-m3` 与 rerank 的 `bge-reranker-v2-m3` 是硬依赖(api 容器 depends_on 两者的 healthcheck,模型缺失时它们无法变 healthy,api 不会启动);`nli-deberta-v3-base` 可选,缺失只影响记忆矛盾覆盖。

## 部署步骤

### 1. 拉取代码到服务器

```bash
git clone <仓库地址> tiangong
cd tiangong
```

### 2. 生成安全密钥

```bash
# JWT 签名密钥
openssl rand -hex 32
# LLM key 加密密钥(base64 编码 32 字节)
openssl rand -base64 32
```

记下这两个值,下一步填入配置。

### 3. 填写生产配置

```bash
cp .env.production.example .env.production
```

编辑 `.env.production`,**至少改这些项**:

| 变量 | 改成什么 |
|---|---|
| `INTRANET_URL` | 团队访问地址,如 `http://192.168.1.100` 或 `http://intranet.yourcorp.local` |
| `COOKIE_DOMAIN` | 上面 URL 的主机部分,如 `192.168.1.100` 或 `intranet.yourcorp.local` |
| `CORS_ORIGINS` | 与 `INTRANET_URL` 一致 |
| `JWT_SECRET` | 第 2 步生成的 hex 串 |
| `ENCRYPTION_KEY` | 第 2 步生成的 base64 串 |
| `MINIO_SECRET_KEY` | 改掉默认的 `tiangong12345` |
| `GLM_API_KEY` | 你的智谱 API Key(全局默认 Key,用户也可在设置页配自己的自定义配置覆盖) |
| `NEXT_PUBLIC_API_URL` | 浏览器能访问到的 API 地址,如 `http://192.168.1.100:8000` |

### 4. 启动全部服务

```bash
docker compose --env-file .env.production --profile full up -d --build
```

> api / web 挂在 compose 的 `full` profile 下,必须带 `--profile full` 才会启动(不带则只起数据层与本地微服务)。


> **网络受限环境**:若构建时拉 npm 包超时(报 `Request took ...ms` / `aborted due to timeout`),
> 在 `.env.production` 加一行指定镜像源,Web 构建会走它:
> ```
> NPM_REGISTRY=https://registry.npmmirror.com
> ```
> (compose 会把它作为 build-arg 传入 Web 镜像)

首次构建需几分钟(拉镜像 + 装 API/Web 依赖)。完成后查看状态:

```bash
docker compose ps
```

`postgres` / `minio` / `embedding` / `rerank` / `api` / `web` 都应为 `Up` 且 healthcheck 通过(另有 `nli` / `drawio` / `firecrawl` 栈等软依赖服务一并启动)。

### 5. 数据库自动初始化(无需手动)

**API 容器启动时会自动完成数据库初始化**(通过 `entrypoint.sh` 调用 `init_db.py`,全部幂等):

- ✅ 跑全部 alembic 迁移到 head(建表 + pgvector 扩展,已在 head 则跳过)
- ✅ 创建首个管理员(读 `INIT_ADMIN_*` 环境变量,已存在则跳过)
- ✅ seed 默认交底书模板 + 默认评分 Rubric(已存在则跳过)

因此**不需要手动跑迁移或建 admin**——`.env.production` 里的 `INIT_ADMIN_*` 配好即可,`docker compose up` 一键起,起来就是可用系统。

查看初始化日志确认:

```bash
docker compose logs api | grep -E "迁移到 head|管理员|就绪|初始化完成"
```

### 6. 验证

浏览器打开 `INTRANET_URL`(默认 3000 端口由 compose 映射),用 `.env.production` 里 `INIT_ADMIN_*` 配置的 admin 账号登录。

## 跨 host cookie 传递(GOTCHAS F4)

天工用 httpOnly cookie 传 JWT。**cookie 的 `domain` 必须与浏览器访问的 host 匹配**,否则浏览器丢弃 cookie → 登录态丢失。

| 场景 | `COOKIE_DOMAIN` | 结果 |
|---|---|---|
| 浏览器访问 `http://192.168.1.100:3000` | `192.168.1.100` | ✅ |
| 浏览器访问 `http://intranet.local:3000` | `intranet.local` | ✅ |
| `COOKIE_DOMAIN=localhost`(默认未改) | 浏览器在内网 IP 访问 | ❌ 登录后立刻被踢回登录页 |

**口诀:`COOKIE_DOMAIN` = 浏览器地址栏的主机名(去掉协议和端口)。**

## 关闭了开放注册

内部产品化后,**开放注册已关闭**。新账号两种方式:

1. **admin 直接创建**:admin 登录 → 后台 → 用户管理 → 创建用户
2. **邀请码**:admin 在后台生成邀请码 → 发给同事 → 同事在注册页凭码注册

(注:账号发放机制随差距①交付,本部署文档对应容器化版本。)

## 常用运维命令

```bash
# 查看日志
docker compose logs -f api
docker compose logs -f web

# 重启某服务
docker compose restart api

# 更新代码后重新部署
git pull && docker compose --env-file .env.production --profile full up -d --build

# 停止全部
docker compose down

# 停止并删除数据卷(⚠️ 清空所有数据,慎用)
docker compose down -v
```

## 备份

天工业务数据分布在两个卷:`pgdata`(数据库 + pgvector)和 `miniodata`(上传文件)。其余卷(`embdata` / `rerankdata` 为模型运行缓存,`firecrawlpgdata` 为 firecrawl 内部任务队列)不含业务数据,可不备份。

```bash
# 备份数据库
docker compose exec postgres pg_dump -U tiangong tiangong > backup_$(date +%F).sql

# 备份 MinIO 卷(停服后拷贝,或用 mc 客户端在线同步)
docker run --rm -v tiangong_miniodata:/data -v $(pwd):/backup alpine \
  tar czf /backup/miniodata_$(date +%F).tar.gz -C /data .
```

## 后续:加 HTTPS(可选)

内网 HTTP 已够用。若需 HTTPS(如跨子域、更严格安全要求),推荐在 compose 前面加一层 **Caddy**,自动签发内部证书,无需改应用代码:

```bash
# 概念示意,具体配置按 Caddy 文档
caddy reverse-proxy --from https://intranet.yourcorp.local --to localhost:3000
```

届时把 `.env.production` 的 `COOKIE_SECURE=true`,`CORS_ORIGINS` 改为 `https://...`。
