# 计划 2：前端地基 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 搭建天工前端地基——Next.js 工程、API client、登录注册、工作台（项目列表）、项目 CRUD，连通计划 1 后端 API，产出端到端可跑的前端骨架。

**Architecture:** Next.js 14 (App Router) + TypeScript + shadcn/ui + Tailwind CSS。客户端渲染为主（认证靠 httpOnly cookie，无需 SSR 取 cookie）。TanStack Query 管服务端状态，Zustand 管 UI 状态。API client 用原生 fetch 封装（credentials: 'include' 带 cookie）。

**Tech Stack:** Next.js 14+ · TypeScript · pnpm · Tailwind CSS · shadcn/ui · TanStack Query · Zustand · Vitest（单元）· Playwright（E2E，后续）

**Spec reference:** `docs/superpowers/specs/2026-07-13-tiangong-mvp-design.md` v1.5
- 覆盖：路线图阶段 0（前端脚手架）+ 阶段 1（前端登录工作台）
- 后端 API：计划 1 已交付（`/api/v1/auth/*`、`/api/v1/projects/*`）

---

## 后端 API 依赖（计划 1 已交付）

| 端点 | 方法 | 说明 | 认证 |
|---|---|---|---|
| `/api/v1/auth/register` | POST | 注册，返回 UserRead | 否 |
| `/api/v1/auth/login` | POST | 登录，设 httpOnly cookie | 否 |
| `/api/v1/auth/logout` | POST | 登出，清 cookie | 否 |
| `/api/v1/auth/me` | GET | 当前用户 | 是 |
| `/api/v1/projects` | GET/POST | 列表/创建 | 是 |
| `/api/v1/projects/{id}` | GET/PATCH/DELETE | 详情/更新/删除 | 是 |
| `/api/v1/health` | GET | 健康检查 | 否 |

错误响应统一格式：`{ "code": "xxx", "message": "xxx" }`

---

## 文件结构

```
apps/web/
├── package.json
├── tsconfig.json
├── next.config.mjs
├── tailwind.config.ts
├── postcss.config.mjs
├── components.json              # shadcn/ui 配置
├── .env.local                   # NEXT_PUBLIC_API_URL
├── src/
│   ├── app/
│   │   ├── layout.tsx           # 根 layout（QueryProvider）
│   │   ├── globals.css          # Tailwind + shadcn 变量
│   │   ├── page.tsx             # 首页（重定向到 /login 或 /dashboard）
│   │   ├── (auth)/
│   │   │   ├── login/page.tsx   # 登录页
│   │   │   └── register/page.tsx # 注册页
│   │   └── (app)/
│   │       ├── layout.tsx       # 应用布局（顶栏 + 鉴权守卫）
│   │       └── dashboard/
│   │           └── page.tsx     # 工作台（项目列表）
│   ├── components/
│   │   ├── ui/                  # shadcn/ui 组件（button/input/card/dialog...）
│   │   ├── auth-form.tsx        # 登录/注册表单
│   │   ├── project-list.tsx     # 项目列表
│   │   ├── project-card.tsx     # 项目卡片
│   │   ├── create-project-dialog.tsx # 新建项目弹窗
│   │   └── navbar.tsx           # 顶栏（logo + 用户菜单）
│   ├── lib/
│   │   ├── api.ts               # API client（fetch 封装）
│   │   ├── queries.ts           # TanStack Query hooks
│   │   └── utils.ts             # cn() 等
│   ├── stores/
│   │   └── auth.ts              # Zustand: 当前用户状态
│   └── types/
│       └── api.ts               # API 类型定义（与后端 schema 对齐）
└── tests/                       # Vitest（后续补）
```

**关键设计决策**：
1. **客户端渲染为主**：认证用 httpOnly cookie，前端不需 SSR 取 cookie。用 `'use client'` 组件处理认证态。
2. **API client 用 fetch**：不引 axios，原生 fetch + `credentials: 'include'` 带 cookie，简单够用。
3. **TanStack Query**：管 projects 列表等服务端状态（缓存、loading、错误）。
4. **路由分组**：`(auth)` 无布局、`(app)` 有顶栏布局 + 鉴权守卫。
5. **CORS**：后端已配 `CORS_ORIGINS=http://localhost:3000`，开发期前端 3000 端口。

---

## 任务 0：Next.js 脚手架与 shadcn/ui

**Files:**
- Create: `apps/web/`（整个 Next.js 工程）

- [ ] **Step 1: 创建 Next.js 工程**

Run（仓库根）:
```bash
cd apps && pnpm create next-app@latest web --typescript --tailwind --eslint --app --src-dir --import-alias "@/*" --no-turbopack
```

交互提示全部选默认（若有无障碍 `--use-pnpm` 标志则加）。完成后 `apps/web/` 应有完整 Next.js 工程。

- [ ] **Step 2: 验证开发服务器能启动**

Run:
```bash
cd apps/web && pnpm dev
```
Expected: 访问 `http://localhost:3000` 看到 Next.js 默认页。确认后 Ctrl+C 停止。

- [ ] **Step 3: 初始化 shadcn/ui**

Run:
```bash
cd apps/web && pnpm dlx shadcn@latest init -d
```
Expected: 生成 `components.json`、`lib/utils.ts`、更新 `globals.css` 的 CSS 变量。

- [ ] **Step 4: 添加基础 shadcn 组件**

Run:
```bash
cd apps/web && pnpm dlx shadcn@latest add button input card label dialog form sonner -y
```
Expected: `src/components/ui/` 下生成对应组件文件。

- [ ] **Step 5: 配置 `.env.local`**

Create `apps/web/.env.local`:
```bash
NEXT_PUBLIC_API_URL=http://localhost:8000
```

- [ ] **Step 6: 清理默认页面**

将 `src/app/page.tsx` 替换为最小首页（后续任务改成重定向）:
```tsx
export default function Home() {
  return (
    <main className="flex min-h-screen items-center justify-center">
      <p className="text-lg">天工 TianGong</p>
    </main>
  )
}
```

- [ ] **Step 7: 验证仍可启动 + Commit**

Run: `cd apps/web && pnpm dev`，确认无报错后停止。

```bash
git add apps/web/
git commit -m "chore: 初始化 Next.js 前端脚手架与 shadcn/ui"
```

---

## 任务 1：API 类型定义与 client

**Files:**
- Create: `apps/web/src/types/api.ts`
- Create: `apps/web/src/lib/api.ts`
- Create: `apps/web/src/lib/queries.ts`

- [ ] **Step 1: 定义 API 类型**

Create `apps/web/src/types/api.ts`:
```typescript
// 与后端 schemas 对齐

export interface User {
  id: string
  email: string
  name: string
  role: string
}

export interface Project {
  id: string
  title: string
  stage: string
  status: string
  progress_pct: number
  metadata: Record<string, unknown> | null
  created_at: string
  updated_at: string
}

export interface ProjectCreate {
  title: string
  template_id?: string | null
  metadata?: Record<string, unknown> | null
}

export interface ProjectUpdate {
  title?: string
  metadata?: Record<string, unknown> | null
}

export interface ApiError {
  code: string
  message: string
}

export interface RegisterRequest {
  email: string
  password: string
  name: string
}

export interface LoginRequest {
  email: string
  password: string
}
```

- [ ] **Step 2: 实现 API client**

Create `apps/web/src/lib/api.ts`:
```typescript
import type {
  ApiError,
  LoginRequest,
  Project,
  ProjectCreate,
  ProjectUpdate,
  RegisterRequest,
  User,
} from '@/types/api'

const BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

async function request<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const res = await fetch(`${BASE}/api/v1${path}`, {
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  })

  if (!res.ok) {
    let err: ApiError
    try {
      err = (await res.json()) as ApiError
    } catch {
      err = { code: 'unknown', message: `HTTP ${res.status}` }
    }
    throw err
  }

  // 204 No Content
  if (res.status === 204) {
    return undefined as T
  }
  return res.json() as Promise<T>
}

// ── 认证 ──
export const api = {
  register: (data: RegisterRequest) =>
    request<User>('/auth/register', { method: 'POST', body: JSON.stringify(data) }),

  login: (data: LoginRequest) =>
    request<{ access_token: string }>('/auth/login', { method: 'POST', body: JSON.stringify(data) }),

  logout: () => request<{ message: string }>('/auth/logout', { method: 'POST' }),

  me: () => request<User>('/auth/me'),

  // ── 项目 ──
  listProjects: () => request<Project[]>('/projects'),

  createProject: (data: ProjectCreate) =>
    request<Project>('/projects', { method: 'POST', body: JSON.stringify(data) }),

  getProject: (id: string) => request<Project>(`/projects/${id}`),

  updateProject: (id: string, data: ProjectUpdate) =>
    request<Project>(`/projects/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),

  deleteProject: (id: string) =>
    request<void>(`/projects/${id}`, { method: 'DELETE' }),
}
```

- [ ] **Step 3: 实现 TanStack Query hooks**

先装依赖:
```bash
cd apps/web && pnpm add @tanstack/react-query
```

Create `apps/web/src/lib/queries.ts`:
```typescript
'use client'

import {
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query'

import { api } from '@/lib/api'
import type { ProjectCreate } from '@/types/api'

export const queryKeys = {
  projects: ['projects'] as const,
  me: ['me'] as const,
}

// ── 项目 ──
export function useProjects() {
  return useQuery({
    queryKey: queryKeys.projects,
    queryFn: api.listProjects,
  })
}

export function useCreateProject() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: ProjectCreate) => api.createProject(data),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.projects }),
  })
}

export function useDeleteProject() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.deleteProject(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.projects }),
  })
}

// ── 用户 ──
export function useMe() {
  return useQuery({
    queryKey: queryKeys.me,
    queryFn: api.me,
    retry: false,
  })
}
```

- [ ] **Step 4: Commit**

```bash
git add apps/web/src/types/ apps/web/src/lib/ apps/web/package.json apps/web/pnpm-lock.yaml
git commit -m "feat: API 类型定义、fetch client 与 TanStack Query hooks"
```

---

## 任务 2：根 layout + QueryProvider + 鉴权状态

**Files:**
- Create: `apps/web/src/app/providers.tsx`
- Modify: `apps/web/src/app/layout.tsx`
- Create: `apps/web/src/stores/auth.ts`

- [ ] **Step 1: 实现 QueryProvider**

Create `apps/web/src/app/providers.tsx`:
```tsx
'use client'

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useState } from 'react'

import { Toaster } from '@/components/ui/sonner'

export function Providers({ children }: { children: React.ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: { staleTime: 30_000, refetchOnWindowFocus: false },
        },
      }),
  )
  return (
    <QueryClientProvider client={client}>
      {children}
      <Toaster />
    </QueryClientProvider>
  )
}
```

- [ ] **Step 2: 改写根 layout**

Replace `apps/web/src/app/layout.tsx`:
```tsx
import type { Metadata } from 'next'

import { Providers } from '@/app/providers'
import './globals.css'

export const metadata: Metadata = {
  title: '天工 TianGong',
  description: 'AI 驱动的专利交底书撰写智能体',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="zh-CN">
      <body className="min-h-screen bg-background antialiased">
        <Providers>{children}</Providers>
      </body>
    </html>
  )
}
```

- [ ] **Step 3: 实现 auth store（Zustand）**

装 zustand:
```bash
cd apps/web && pnpm add zustand
```

Create `apps/web/src/stores/auth.ts`:
```typescript
import { create } from 'zustand'

import type { User } from '@/types/api'

interface AuthState {
  user: User | null
  setUser: (user: User | null) => void
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  setUser: (user) => set({ user }),
}))
```

- [ ] **Step 4: 首页重定向逻辑**

Replace `apps/web/src/app/page.tsx`:
```tsx
import { redirect } from 'next/navigation'

export default function Home() {
  redirect('/dashboard')
}
```

- [ ] **Step 5: 验证启动 + Commit**

Run: `cd apps/web && pnpm dev`，确认无报错，访问 localhost:3000 会重定向到 /dashboard（此时 dashboard 还没建，会 404，正常）。

```bash
git add apps/web/src/app/providers.tsx apps/web/src/app/layout.tsx apps/web/src/app/page.tsx apps/web/src/stores/ apps/web/package.json apps/web/pnpm-lock.yaml
git commit -m "feat: 根 layout + QueryProvider + auth store + 首页重定向"
```

---

## 任务 3：登录注册页

**Files:**
- Create: `apps/web/src/components/auth-form.tsx`
- Create: `apps/web/src/app/(auth)/login/page.tsx`
- Create: `apps/web/src/app/(auth)/register/page.tsx`

- [ ] **Step 1: 实现 auth-form 组件**

Create `apps/web/src/components/auth-form.tsx`:
```tsx
'use client'

import { useRouter } from 'next/navigation'
import { useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { api } from '@/lib/api'
import { useAuthStore } from '@/stores/auth'

interface AuthFormProps {
  mode: 'login' | 'register'
}

export function AuthForm({ mode }: AuthFormProps) {
  const router = useRouter()
  const setUser = useAuthStore((s) => s.setUser)
  const [loading, setLoading] = useState(false)
  const isRegister = mode === 'register'

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault()
    setLoading(true)
    const form = new FormData(e.currentTarget)
    const email = String(form.get('email'))
    const password = String(form.get('password'))
    const name = String(form.get('name') || '')

    try {
      if (isRegister) {
        await api.register({ email, password, name })
      }
      await api.login({ email, password })
      const user = await api.me()
      setUser(user)
      toast.success('登录成功')
      router.push('/dashboard')
    } catch (err) {
      toast.error((err as { message?: string })?.message || '操作失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <form onSubmit={onSubmit} className="space-y-4 w-full max-w-sm">
      {isRegister && (
        <div className="space-y-2">
          <Label htmlFor="name">姓名</Label>
          <Input id="name" name="name" required placeholder="你的名字" />
        </div>
      )}
      <div className="space-y-2">
        <Label htmlFor="email">邮箱</Label>
        <Input id="email" name="email" type="email" required placeholder="you@example.com" />
      </div>
      <div className="space-y-2">
        <Label htmlFor="password">密码</Label>
        <Input id="password" name="password" type="password" required minLength={8} placeholder="至少 8 位" />
      </div>
      <Button type="submit" className="w-full" disabled={loading}>
        {loading ? '处理中...' : isRegister ? '注册并登录' : '登录'}
      </Button>
    </form>
  )
}
```

- [ ] **Step 2: 登录页**

Create `apps/web/src/app/(auth)/login/page.tsx`:
```tsx
import Link from 'next/link'

import { AuthForm } from '@/components/auth-form'

export default function LoginPage() {
  return (
    <main className="flex min-h-screen items-center justify-center px-4">
      <div className="w-full max-w-sm space-y-6">
        <div className="text-center space-y-2">
          <h1 className="text-2xl font-bold">天工 TianGong</h1>
          <p className="text-sm text-muted-foreground">登录你的账户</p>
        </div>
        <AuthForm mode="login" />
        <p className="text-center text-sm text-muted-foreground">
          还没账户？{' '}
          <Link href="/register" className="text-primary underline">注册</Link>
        </p>
      </div>
    </main>
  )
}
```

- [ ] **Step 3: 注册页**

Create `apps/web/src/app/(auth)/register/page.tsx`:
```tsx
import Link from 'next/link'

import { AuthForm } from '@/components/auth-form'

export default function RegisterPage() {
  return (
    <main className="flex min-h-screen items-center justify-center px-4">
      <div className="w-full max-w-sm space-y-6">
        <div className="text-center space-y-2">
          <h1 className="text-2xl font-bold">天工 TianGong</h1>
          <p className="text-sm text-muted-foreground">创建新账户</p>
        </div>
        <AuthForm mode="register" />
        <p className="text-center text-sm text-muted-foreground">
          已有账户？{' '}
          <Link href="/login" className="text-primary underline">登录</Link>
        </p>
      </div>
    </main>
  )
}
```

- [ ] **Step 4: 验证 + Commit**

Run: `cd apps/web && pnpm dev`
- 访问 `/login` 看到登录表单
- 访问 `/register` 看到注册表单（含姓名字段）

```bash
git add apps/web/src/components/auth-form.tsx "apps/web/src/app/(auth)/"
git commit -m "feat: 登录注册页面与表单组件"
```

---

## 任务 4：应用布局 + 鉴权守卫 + 顶栏

**Files:**
- Create: `apps/web/src/components/navbar.tsx`
- Create: `apps/web/src/app/(app)/layout.tsx`

- [ ] **Step 1: 实现 navbar**

Create `apps/web/src/components/navbar.tsx`:
```tsx
'use client'

import { useRouter } from 'next/navigation'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { api } from '@/lib/api'
import { useAuthStore } from '@/stores/auth'

export function Navbar() {
  const router = useRouter()
  const user = useAuthStore((s) => s.user)
  const setUser = useAuthStore((s) => s.setUser)

  async function handleLogout() {
    try {
      await api.logout()
      setUser(null)
      toast.success('已登出')
      router.push('/login')
    } catch {
      toast.error('登出失败')
    }
  }

  return (
    <header className="border-b bg-background">
      <div className="mx-auto flex h-14 max-w-5xl items-center justify-between px-4">
        <span className="font-bold">天工 TianGong</span>
        {user && (
          <div className="flex items-center gap-3 text-sm">
            <span className="text-muted-foreground">{user.email}</span>
            <Button variant="ghost" size="sm" onClick={handleLogout}>登出</Button>
          </div>
        )}
      </div>
    </header>
  )
}
```

- [ ] **Step 2: 实现应用 layout（含鉴权守卫）**

Create `apps/web/src/app/(app)/layout.tsx`:
```tsx
'use client'

import { useRouter } from 'next/navigation'
import { useEffect } from 'react'

import { Navbar } from '@/components/navbar'
import { api } from '@/lib/api'
import { useAuthStore } from '@/stores/auth'

export default function AppLayout({
  children,
}: {
  children: React.ReactNode
}) {
  const router = useRouter()
  const user = useAuthStore((s) => s.user)
  const setUser = useAuthStore((s) => s.setUser)

  useEffect(() => {
    // 进入应用页面前校验登录态
    if (user) return
    api
      .me()
      .then((u) => setUser(u))
      .catch(() => router.replace('/login'))
  }, [user, setUser, router])

  if (!user) {
    return (
      <div className="flex min-h-screen items-center justify-center text-muted-foreground">
        加载中...
      </div>
    )
  }

  return (
    <div className="min-h-screen">
      <Navbar />
      <main className="mx-auto max-w-5xl px-4 py-8">{children}</main>
    </div>
  )
}
```

- [ ] **Step 3: Commit**

```bash
git add apps/web/src/components/navbar.tsx "apps/web/src/app/(app)/layout.tsx"
git commit -m "feat: 应用布局、鉴权守卫与顶栏（登录态校验）"
```

---

## 任务 5：工作台（项目列表）

**Files:**
- Create: `apps/web/src/components/project-card.tsx`
- Create: `apps/web/src/components/create-project-dialog.tsx`
- Create: `apps/web/src/components/project-list.tsx`
- Create: `apps/web/src/app/(app)/dashboard/page.tsx`

- [ ] **Step 1: 项目卡片**

Create `apps/web/src/components/project-card.tsx`:
```tsx
'use client'

import { useRouter } from 'next/navigation'
import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { useDeleteProject } from '@/lib/queries'
import type { Project } from '@/types/api'

const STATUS_LABEL: Record<string, string> = {
  draft: '草稿',
  in_progress: '进行中',
  completed: '已完成',
  archived: '已归档',
}

export function ProjectCard({ project }: { project: Project }) {
  const router = useRouter()
  const del = useDeleteProject()

  function handleDelete() {
    if (!confirm(`确认删除「${project.title}」？此操作不可恢复。`)) return
    del.mutate(project.id, {
      onSuccess: () => toast.success('已删除'),
      onError: () => toast.error('删除失败'),
    })
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-base cursor-pointer" onClick={() => router.push(`/projects/${project.id}`)}>
          {project.title}
        </CardTitle>
        <Badge variant="secondary">{STATUS_LABEL[project.status] || project.status}</Badge>
      </CardHeader>
      <CardContent className="space-y-2">
        <p className="text-xs text-muted-foreground">
          阶段：{project.stage} · 进度 {project.progress_pct}%
        </p>
        <p className="text-xs text-muted-foreground">
          更新于 {new Date(project.updated_at).toLocaleString('zh-CN')}
        </p>
        <Button variant="ghost" size="sm" className="text-destructive" onClick={handleDelete} disabled={del.isPending}>
          删除
        </Button>
      </CardContent>
    </Card>
  )
}
```

- [ ] **Step 2: 添加 badge 组件（shadcn）**

Run:
```bash
cd apps/web && pnpm dlx shadcn@latest add badge -y
```

- [ ] **Step 3: 新建项目弹窗**

Create `apps/web/src/components/create-project-dialog.tsx`:
```tsx
'use client'

import { useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useCreateProject } from '@/lib/queries'

export function CreateProjectDialog() {
  const create = useCreateProject()
  const [open, setOpen] = useState(false)
  const [title, setTitle] = useState('')

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!title.trim()) return
    create.mutate(
      { title: title.trim() },
      {
        onSuccess: () => {
          toast.success('项目已创建')
          setTitle('')
          setOpen(false)
        },
        onError: () => toast.error('创建失败'),
      },
    )
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button>新建项目</Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>新建交底书项目</DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="title">项目名称</Label>
            <Input
              id="title"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="给你的发明起个名字"
              autoFocus
            />
          </div>
          <DialogFooter>
            <Button type="submit" disabled={create.isPending || !title.trim()}>
              {create.isPending ? '创建中...' : '创建'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
```

- [ ] **Step 4: 项目列表**

Create `apps/web/src/components/project-list.tsx`:
```tsx
'use client'

import { CreateProjectDialog } from '@/components/create-project-dialog'
import { ProjectCard } from '@/components/project-card'
import { useProjects } from '@/lib/queries'

export function ProjectList() {
  const { data: projects, isLoading, isError } = useProjects()

  if (isLoading) return <p className="text-muted-foreground">加载中...</p>
  if (isError) return <p className="text-destructive">加载失败，请重试</p>

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold">我的项目</h1>
        <CreateProjectDialog />
      </div>

      {projects.length === 0 ? (
        <div className="rounded-lg border border-dashed p-12 text-center text-muted-foreground">
          还没有项目，点击右上角「新建项目」开始你的第一份交底书
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {projects.map((p) => (
            <ProjectCard key={p.id} project={p} />
          ))}
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 5: 工作台页**

Create `apps/web/src/app/(app)/dashboard/page.tsx`:
```tsx
import { ProjectList } from '@/components/project-list'

export default function DashboardPage() {
  return <ProjectList />
}
```

- [ ] **Step 6: Commit**

```bash
git add apps/web/src/components/ apps/web/src/app/ apps/web/components.json
git commit -m "feat: 工作台（项目列表 + 新建/删除项目）"
```

---

## 任务 6：端到端验证

- [ ] **Step 1: 启动后端**

Terminal 1:
```bash
cd apps/api && uv run uvicorn app.main:app --reload
```
Expected: 后端运行在 :8000。

- [ ] **Step 2: 启动前端**

Terminal 2:
```bash
cd apps/web && pnpm dev
```
Expected: 前端运行在 :3000。

- [ ] **Step 3: 手动验证完整流程**

在浏览器：
1. 访问 `http://localhost:3000` → 重定向到 `/dashboard` → 守卫检测未登录 → 跳 `/login`
2. 点击「注册」→ 填邮箱/密码/姓名 → 注册成功 → 跳转 `/dashboard`
3. 看到「还没有项目」空状态
4. 点「新建项目」→ 填名称 → 创建成功 → 列表出现新项目卡片
5. 点「删除」→ 确认 → 项目消失
6. 点顶栏「登出」→ 跳回 `/login`
7. 用刚注册的账号登录 → 看到 `/dashboard`

- [ ] **Step 4: Commit 验证记录**

```bash
git commit --allow-empty -m "chore: 计划 2 前端地基端到端验证通过

注册→登录→工作台→新建项目→删除项目→登出→重新登录 全流程通过。
连通后端计划 1 API。"
```

---

## 完成标准

计划 2 完成后，应满足：

- [ ] `apps/web/` Next.js 工程完整，shadcn/ui 就位
- [ ] `pnpm dev` 可启动，访问 localhost:3000 正常
- [ ] 登录/注册页可用，连通后端认证 API
- [ ] 工作台显示项目列表，可新建/删除项目
- [ ] 鉴权守卫：未登录跳转 `/login`
- [ ] 顶栏登出可用
- [ ] 端到端全流程跑通

## 后续计划衔接

| 后续计划 | 本计划已预埋 |
|---|---|
| 计划 3 模板与编辑器 | 项目卡片点击跳 `/projects/{id}`（详情页待建）、API client、Query hooks |
| 计划 4 AI 引擎 | auth store、鉴权守卫、布局框架 |
| 计划 7 管理 | `User.role` 类型已定义，可按角色渲染管理入口 |
