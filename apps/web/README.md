# 天工前端（web）

天工 AI 专利交底书撰写智能体的前端应用。

## 技术栈

Next.js · TypeScript · Tailwind CSS · shadcn/ui 3.x · TanStack Query · Zustand · pnpm

## 开发

```bash
pnpm install
pnpm dev          # http://localhost:3000
pnpm build        # 生产构建
```

环境变量见 `.env.local`（`NEXT_PUBLIC_API_URL` 指向后端地址）。

## 目录结构

```
src/
├── app/            # App Router（(auth) 登录注册组 / (app) 应用组）
├── components/     # 业务组件 + ui/（shadcn）
├── lib/            # API client、TanStack Query hooks
├── stores/         # Zustand 状态
└── types/          # 类型定义
```

详细架构请见[项目根 README](../../README.md)与[设计文档](../../docs/superpowers/specs/2026-07-13-tiangong-mvp-design.md)。
