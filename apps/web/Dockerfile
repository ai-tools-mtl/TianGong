# 天工 Web 镜像
# 多阶段构建,基于 Next.js standalone 输出,运行镜像精简
# 参考:https://nextjs.org/docs/app/api-reference/config/next-config-js/output

FROM node:22-alpine AS base

# 可选:通过 build-arg 指定 npm 镜像源(内网或网络受限环境用)
# 默认官方源;部署时:--build-arg NPM_REGISTRY=https://registry.npmmirror.com
ARG NPM_REGISTRY=https://registry.npmjs.org

# --- deps 阶段:装依赖(利用层缓存)---
FROM base AS deps
RUN apk add --no-cache libc6-compat
WORKDIR /app
# pnpm-workspace.yaml 含 build 审批配置(pnpm 11 默认阻止 build script),
# 必须在 install 前拷入,否则 sharp 等 native 依赖 build 被忽略导致 --frozen-lockfile 报错
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN corepack enable pnpm && \
    pnpm config set registry "$NPM_REGISTRY" && \
    pnpm install --frozen-lockfile

# --- builder 阶段:构建 ---
FROM base AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# NEXT_PUBLIC_* 在 build 时内联进产物,需在构建阶段注入
# 通过 build-arg 传入,内网部署时由 compose 注入
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL

RUN corepack enable pnpm && \
    pnpm config set registry "$NPM_REGISTRY" && \
    pnpm build

# --- runner 阶段:精简运行镜像 ---
FROM base AS runner
WORKDIR /app

ENV NODE_ENV=production

# Next.js standalone 运行推荐非 root
RUN addgroup --system --gid 1001 nodejs && \
    adduser --system --uid 1001 nextjs

# 拷 standalone 产物 + static 资源 + public
COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs

EXPOSE 3000

ENV PORT=3000 \
    HOSTNAME="0.0.0.0"

# standalone 产物自带 server.js
CMD ["node", "server.js"]
