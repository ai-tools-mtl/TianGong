# Firecrawl 网页摄入前端 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给天工前端加 Firecrawl 网页摄入完整 UI——用户端抓取入口 + crawl 任务追踪 + admin 全局库抓取 + admin Firecrawl 配置页 + 控制台卡片导航。

**Architecture:** 共享组件 scope 参数化(用户端 personal / admin global 共用 WebIngestDialog + IngestJobTracker)。数据层走现有 request() wrapper + react-query(轮询用 refetchInterval)。基础组件 Progress/Collapsible 手写(GOTCHAS F8:CLI 装不了 shadcn 组件)。

**Tech Stack:** Next.js 16 + React 19 + TypeScript 5 + shadcn/ui + TanStack Query 5 + Tailwind v4 + sonner + lucide-react

**Spec:** `docs/superpowers/specs/2026-07-27-firecrawl-web-ingestion-frontend-design.md`

---

## 文件结构

### 新建文件(7 个)

| 文件 | 职责 |
|---|---|
| `apps/web/src/components/ui/progress.tsx` | 进度条基础组件(轨道色 --track) |
| `apps/web/src/components/ui/collapsible.tsx` | 折叠组件(原生 details,高级选项用) |
| `apps/web/src/lib/source-type-labels.ts` | source_type 中文 label 映射(共享) |
| `apps/web/src/components/web-ingest-dialog.tsx` | URL 输入 + mode 选择 Dialog(scope 参数化) |
| `apps/web/src/components/ingest-job-card.tsx` | 单个任务卡片(进度条 + 状态) |
| `apps/web/src/components/ingest-job-tracker.tsx` | 任务追踪区(按 scope 过滤 + dismiss) |
| `apps/web/src/app/(app)/admin/console/firecrawl/page.tsx` | Firecrawl 配置页 |

### 改动文件(6 个)

| 文件 | 改动 |
|---|---|
| `apps/api/app/api/knowledge.py` | `_file_out` 加 url 字段(前置后端 1 行) |
| `apps/web/src/types/api.ts` | 加 WebIngestJob/WebIngestResult/FirecrawlSettings + KnowledgeFile.url |
| `apps/web/src/lib/api.ts` | 加 ingestWeb/getIngestJob/listIngestJobs/getFirecrawlConfig/setFirecrawlConfig |
| `apps/web/src/lib/queries.ts` | 加 useIngestWeb/useIngestJobs/useFirecrawlConfig/useSaveFirecrawlConfig + queryKeys |
| `apps/web/src/components/knowledge-manager.tsx` | 加抓取按钮 + IngestJobTracker + source_type label |
| `apps/web/src/app/(app)/admin/content/knowledge/page.tsx` | 加抓取按钮 + IngestJobTracker + source_type label |
| `apps/web/src/app/(app)/admin/console/page.tsx` | redirect 改卡片网格 |

---

## 任务依赖

```
Task 0 (后端前置) → Task 1 (types) → Task 2 (api) → Task 3 (queries)
Task 4 (Progress) ─┐
Task 5 (Collapsible) ─┤
Task 6 (source-type-labels) ─┤→ Task 8 (IngestJobCard) → Task 9 (IngestJobTracker)
Task 7 (WebIngestDialog) ─┘
                                                              ↓
                                          Task 10 (用户端集成) + Task 11 (admin 端集成)
                                                              ↓
                                                   Task 12 (Firecrawl 配置页)
                                                              ↓
                                                   Task 13 (控制台卡片导航)
```

---

## Task 0: 后端前置 — `_file_out` 加 url 字段

**Files:**
- Modify: `apps/api/app/api/knowledge.py:68-78`

- [ ] **Step 1: 改 `_file_out` 函数**

打开 `apps/api/app/api/knowledge.py`,找到 `_file_out` 函数(第 68-78 行),在 `source_type` 之后、`created_at` 之前加 `url` 字段:

```python
def _file_out(kf: KnowledgeFile) -> dict:
    return {
        "id": str(kf.id),
        "uploader_id": str(kf.uploader_id),
        "scope": kf.scope,
        "filename": kf.filename,
        "mime_type": kf.mime_type,
        "size": kf.size,
        "source_type": kf.source_type,
        "url": kf.url,  # 新增:网页来源的原 URL(external_web 才有值,其他为 None)
        "created_at": kf.created_at.isoformat(),
    }
```

- [ ] **Step 2: 跑后端测试确认零回归**

Run: `cd apps/api && uv run pytest tests/test_knowledge*.py tests/test_web_ingestion*.py -v`
Expected: 全部通过(_file_out 加字段不破坏现有测试,新字段对老调用方是增量)

- [ ] **Step 3: Commit**

```bash
cd "G:\03-Personal-Projects\TianGong"
git add apps/api/app/api/knowledge.py
git commit -m "feat(api): _file_out 补 url 字段(网页摄入前端前置)"
```

---

## Task 1: types/api.ts 扩展

**Files:**
- Modify: `apps/web/src/types/api.ts`

- [ ] **Step 1: 找到 KnowledgeFile 接口位置**

Run: `cd apps/web && grep -n "interface KnowledgeFile" src/types/api.ts`
Expected: 输出行号(约 441 行)

- [ ] **Step 2: 给 KnowledgeFile 加 url 字段**

打开 `apps/web/src/types/api.ts`,找到 `KnowledgeFile` 接口,在 `source_type` 字段后加:

```typescript
export interface KnowledgeFile {
  id: string
  uploader_id: string
  scope: 'personal' | 'global'
  filename: string
  mime_type: string
  size: number
  source_type: string
  url?: string | null  // 新增:网页来源的原 URL(external_web 才有值)
  created_at: string
}
```

- [ ] **Step 3: 在 KnowledgeFile 之后加新类型**

在 `KnowledgeFile` 接口之后(或文件末尾合适位置)加:

```typescript
// 网页摄入任务(对应后端 WebIngestionJob)
export interface WebIngestJob {
  id: string
  url: string
  mode: 'scrape' | 'crawl'
  scope: 'personal' | 'global'
  status: 'pending' | 'running' | 'completed' | 'failed'
  max_pages: number  // crawl 上限(进度计算用)
  pages_fetched: number
  pages_filtered: number
  file_ids: string[]
  error_message: string | null
  created_at: string
  completed_at: string | null
}

// POST /knowledge/ingest/web 的响应(联合类型)
export type WebIngestResult =
  | { kind: 'file'; file: KnowledgeFile }       // scrape 同步
  | { kind: 'job'; job: WebIngestJob }          // crawl 异步

// 网页摄入请求体
export interface WebIngestRequest {
  url: string
  mode: 'scrape' | 'crawl'
  scope: 'personal' | 'global'
  max_pages?: number
}

// Firecrawl 全局配置(GET /admin/console/firecrawl)
export interface FirecrawlSettings {
  enabled: boolean
  api_key_masked: string
  base_url: string
}

// Firecrawl 配置 PUT 请求体
export interface FirecrawlConfigPayload {
  enabled: boolean
  api_key: string
  base_url: string | null
}
```

- [ ] **Step 4: 类型检查**

Run: `cd apps/web && pnpm exec tsc --noEmit 2>&1 | head -20`
Expected: 无新增类型错误(可能有既有的,只要不是本任务引入的)

- [ ] **Step 5: Commit**

```bash
cd "G:\03-Personal-Projects\TianGong"
git add apps/web/src/types/api.ts
git commit -m "feat(web): 加网页摄入 + Firecrawl 配置类型定义"
```

---

## Task 2: lib/api.ts 扩展

**Files:**
- Modify: `apps/web/src/lib/api.ts`(在知识库段 553 行附近追加)

- [ ] **Step 1: 找到知识库段末尾**

Run: `cd apps/web && grep -n "knowledgeFileUrl\|知识库审核" src/lib/api.ts | head -5`
Expected: `knowledgeFileUrl` 在 550 行,审核段从 553 开始。在 553 行(`// ── 知识库审核(admin)──`)之前插入新方法。

- [ ] **Step 2: 在 knowledgeFileUrl 之后、审核段之前插入网页摄入 API**

打开 `apps/web/src/lib/api.ts`,找到 `knowledgeFileUrl`(约 550-551 行),在它之后、`// ── 知识库审核(admin)──` 注释之前插入:

```typescript

  // ── 网页摄入(Firecrawl)──
  ingestWeb: (payload: import('@/types/api').WebIngestRequest) =>
    request<import('@/types/api').WebIngestResult>('/knowledge/ingest/web', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  getIngestJob: (jobId: string) =>
    request<import('@/types/api').WebIngestJob>(`/knowledge/ingest/jobs/${jobId}`),

  listIngestJobs: () =>
    request<import('@/types/api').WebIngestJob[]>('/knowledge/ingest/jobs'),
```

- [ ] **Step 3: 在 admin 段加 Firecrawl 配置 API**

找到 admin LLM 配置段(Run: `grep -n "getGlobalLLM\|setGlobalLLM\|admin/llm-config" src/lib/api.ts`),在它附近(或 admin 段合适位置)加:

```typescript

  // ── Firecrawl 全局配置(admin)──
  getFirecrawlConfig: () =>
    request<import('@/types/api').FirecrawlSettings>('/admin/console/firecrawl'),

  setFirecrawlConfig: (payload: import('@/types/api').FirecrawlConfigPayload) =>
    request<{ ok: true }>('/admin/console/firecrawl', {
      method: 'PUT',
      body: JSON.stringify(payload),
    }),
```

**注意**:用 `import('@/types/api').XXX` 内联类型(对齐现有 `listPersonalKnowledge` 的写法,见 545-548 行),不在文件顶部加 import。

- [ ] **Step 4: 类型检查**

Run: `cd apps/web && pnpm exec tsc --noEmit 2>&1 | grep -i "api.ts" | head -10`
Expected: 无本文件的新增类型错误

- [ ] **Step 5: Commit**

```bash
cd "G:\03-Personal-Projects\TianGong"
git add apps/web/src/lib/api.ts
git commit -m "feat(web): 加网页摄入 + Firecrawl 配置 API 封装"
```

---

## Task 3: lib/queries.ts 扩展

**Files:**
- Modify: `apps/web/src/lib/queries.ts`

- [ ] **Step 1: 扩展 queryKeys**

打开 `apps/web/src/lib/queries.ts`,找到 `queryKeys` 对象(第 26 行开始)。在 `knowledgeGlobal`(第 35 行)之后加:

```typescript
    knowledgePersonal: ['knowledge', 'personal'] as const,
    knowledgeGlobal: ['knowledge', 'global'] as const,
    knowledgeJobs: ['knowledge', 'ingest-jobs'] as const,  // 新增
    knowledgeJob: (id: string) => ['knowledge', 'ingest-jobs', id] as const,  // 新增
```

然后在 `admin` 对象里(第 51-64 行),在 `llmConfig` 之后加:

```typescript
    llmConfig: ['admin', 'llm-config'] as const,
    firecrawlConfig: ['admin', 'firecrawl-config'] as const,  // 新增
```

- [ ] **Step 2: 在知识库 hooks 段加网页摄入 hooks**

找到知识库 hooks 段(约 254-290 行,`usePersonalKnowledge` 附近)。在 `useSubmitKnowledgeReview`(约 284-290 行)之后加:

```typescript

// ── 网页摄入(Firecrawl)──
export function useIngestWeb() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: import('@/types/api').WebIngestRequest) => api.ingestWeb(payload),
    onSuccess: (data) => {
      // crawl 任务进轮询队列;scrape 直接刷文件列表
      qc.invalidateQueries({ queryKey: queryKeys.knowledgeJobs })
      if (data.kind === 'file') {
        qc.invalidateQueries({
          queryKey: data.file.scope === 'global'
            ? queryKeys.knowledgeGlobal
            : queryKeys.knowledgePersonal,
        })
      }
    },
  })
}

export function useIngestJobs() {
  return useQuery({
    queryKey: queryKeys.knowledgeJobs,
    queryFn: () => api.listIngestJobs(),
    // 只要有进行中任务,5s 轮询(比后端 30s 密,UI 更新及时)
    refetchInterval: (query) => {
      const jobs = query.state.data
      const hasActive = jobs?.some(
        (j) => j.status === 'pending' || j.status === 'running',
      )
      return hasActive ? 5000 : false
    },
  })
}
```

- [ ] **Step 3: 在 admin hooks 段加 Firecrawl 配置 hooks**

找到 admin LLM 配置 hooks(Run: `grep -n "useGlobalLLMConfig\|useSaveGlobalLLM" src/lib/queries.ts`)。在它附近加:

```typescript

// ── Firecrawl 全局配置(admin)──
export function useFirecrawlConfig() {
  return useQuery({
    queryKey: queryKeys.admin.firecrawlConfig,
    queryFn: () => api.getFirecrawlConfig(),
  })
}

export function useSaveFirecrawlConfig() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: import('@/types/api').FirecrawlConfigPayload) =>
      api.setFirecrawlConfig(payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.admin.firecrawlConfig })
      // 失效审计缓存(对齐 useSaveGlobalLLM)
      qc.invalidateQueries({ queryKey: queryKeys.admin.all })
    },
  })
}
```

**注意**:`useMutation`/`useQuery`/`useQueryClient` 的 import 应已在文件顶部(现有 hooks 用了)。若没有,补 `import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'`。

- [ ] **Step 4: 类型检查**

Run: `cd apps/web && pnpm exec tsc --noEmit 2>&1 | grep -i "queries.ts" | head -10`
Expected: 无本文件的新增类型错误

- [ ] **Step 5: Commit**

```bash
cd "G:\03-Personal-Projects\TianGong"
git add apps/web/src/lib/queries.ts
git commit -m "feat(web): 加网页摄入 + Firecrawl 配置 react-query hooks"
```

---

## Task 4: Progress 进度条组件

**Files:**
- Create: `apps/web/src/components/ui/progress.tsx`

- [ ] **Step 1: 创建 progress.tsx**

创建 `apps/web/src/components/ui/progress.tsx`:

```typescript
'use client'

import * as React from 'react'

import { cn } from '@/lib/utils'

interface ProgressProps extends React.HTMLAttributes<HTMLDivElement> {
  value?: number
}

const Progress = React.forwardRef<HTMLDivElement, ProgressProps>(
  ({ className, value = 0, ...props }, ref) => (
    <div
      ref={ref}
      role="progressbar"
      aria-valuenow={value}
      aria-valuemin={0}
      aria-valuemax={100}
      className={cn('h-2 w-full overflow-hidden rounded-full', className)}
      style={{ background: 'var(--track)', ...props.style }}
      {...props}
    >
      <div
        className="h-full rounded-full bg-primary transition-all duration-300 ease-out"
        style={{
          width: `${Math.min(100, Math.max(0, value))}%`,
        }}
      />
    </div>
  ),
)
Progress.displayName = 'Progress'

export { Progress }
```

**设计说明**:
- 轨道色用 `var(--track)`(已在 globals.css 定义 `#e8e8ed`)
- 填充用 `bg-primary`(墨黑,不用紫——进度条是产品态)
- 圆角 `rounded-full`,高 8px(`h-2`)
- `transition-all duration-300` 平滑动画
- 无障碍:`role="progressbar"` + aria 属性

- [ ] **Step 2: 类型检查 + 确认 import**

Run: `cd apps/web && pnpm exec tsc --noEmit 2>&1 | grep -i "progress" | head -5`
Expected: 无错误

确认 `cn` 工具函数存在:
Run: `grep -n "export.*cn\|export function cn\|export const cn" src/lib/utils.ts`
Expected: 有输出(`cn` 是 clsx + tailwind-merge 的封装)

- [ ] **Step 3: Commit**

```bash
cd "G:\03-Personal-Projects\TianGong"
git add apps/web/src/components/ui/progress.tsx
git commit -m "feat(web): Progress 进度条组件(shadcn 风格手写)"
```

---

## Task 5: Collapsible 折叠组件

**Files:**
- Create: `apps/web/src/components/ui/collapsible.tsx`

- [ ] **Step 1: 创建 collapsible.tsx**

创建 `apps/web/src/components/ui/collapsible.tsx`:

```typescript
'use client'

import { ChevronDown } from 'lucide-react'

import { cn } from '@/lib/utils'

interface CollapsibleProps {
  /** 触发器内容(显示在箭头后) */
  trigger: React.ReactNode
  /** 展开内容 */
  children: React.ReactNode
  className?: string
}

/**
 * 折叠组件(用原生 <details>,最轻量,无 Radix 依赖)。
 * 箭头展开时旋转 90°(group-open:rotate-90)。
 */
export function Collapsible({ trigger, children, className }: CollapsibleProps) {
  return (
    <details className={cn('group', className)}>
      <summary className="flex cursor-pointer list-none items-center gap-1 text-sm text-muted-foreground transition-colors hover:text-foreground [&::-webkit-details-marker]:hidden">
        <ChevronDown className="size-3.5 transition-transform group-open:rotate-90" />
        {trigger}
      </summary>
      <div className="mt-2">{children}</div>
    </details>
  )
}
```

**设计说明**:
- 用原生 `<details>` + `<summary>`,零 JS 状态管理
- `[&::-webkit-details-marker]:hidden` 隐藏浏览器默认三角
- `group-open:rotate-90` 让 ChevronDown 箭头展开时旋转
- `cursor-pointer` + `hover:text-foreground` 反馈

- [ ] **Step 2: 类型检查**

Run: `cd apps/web && pnpm exec tsc --noEmit 2>&1 | grep -i "collapsible" | head -5`
Expected: 无错误

- [ ] **Step 3: Commit**

```bash
cd "G:\03-Personal-Projects\TianGong"
git add apps/web/src/components/ui/collapsible.tsx
git commit -m "feat(web): Collapsible 折叠组件(原生 details)"
```

---

## Task 6: source-type-labels 共享常量

**Files:**
- Create: `apps/web/src/lib/source-type-labels.ts`

- [ ] **Step 1: 创建 source-type-labels.ts**

创建 `apps/web/src/lib/source-type-labels.ts`:

```typescript
/**
 * KnowledgeFile.source_type 的中文 label 映射(共享)。
 *
 * 后端值(见 apps/api/app/services/knowledge_service.py 的 _source_type_for):
 * - external_pdf / external_docx:用户上传的 docx/pdf
 * - external_web:网页摄入(Firecrawl)
 * - disclosure_export:归档交底书导出
 *
 * 前端 Badge 直接显示 label,而非后端原值(如 external_web → 「网页」)。
 */
export const SOURCE_TYPE_LABELS: Record<string, string> = {
  external_pdf: 'PDF',
  external_docx: 'Word',
  external_web: '网页',
  disclosure_export: '归档',
  external_md: '网页', // 兼容(若后端 _source_type_for 退化到按扩展名)
}

/**
 * 取 source_type 的 label,未知值回退到原值。
 */
export function sourceTypeLabel(sourceType: string): string {
  return SOURCE_TYPE_LABELS[sourceType] ?? sourceType
}
```

- [ ] **Step 2: 类型检查**

Run: `cd apps/web && pnpm exec tsc --noEmit 2>&1 | grep -i "source-type" | head -5`
Expected: 无错误

- [ ] **Step 3: Commit**

```bash
cd "G:\03-Personal-Projects\TianGong"
git add apps/web/src/lib/source-type-labels.ts
git commit -m "feat(web): source_type 中文 label 映射共享常量"
```

---

## Task 7: WebIngestDialog 组件

**Files:**
- Create: `apps/web/src/components/web-ingest-dialog.tsx`

- [ ] **Step 1: 创建 web-ingest-dialog.tsx**

创建 `apps/web/src/components/web-ingest-dialog.tsx`:

```typescript
'use client'

import { useState } from 'react'
import { Globe } from 'lucide-react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Collapsible } from '@/components/ui/collapsible'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useIngestWeb } from '@/lib/queries'
import type { WebIngestRequest } from '@/types/api'

interface WebIngestDialogProps {
  scope: 'personal' | 'global'
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function WebIngestDialog({ scope, open, onOpenChange }: WebIngestDialogProps) {
  const ingest = useIngestWeb()
  const [url, setUrl] = useState('')
  const [mode, setMode] = useState<'scrape' | 'crawl'>('scrape')
  const [maxPages, setMaxPages] = useState(50)

  function resetForm() {
    setUrl('')
    setMode('scrape')
    setMaxPages(50)
  }

  function handleIngest() {
    const payload: WebIngestRequest = {
      url: url.trim(),
      mode,
      scope,
      max_pages: mode === 'crawl' ? maxPages : 1,
    }
    ingest.mutate(payload, {
      onSuccess: (data) => {
        if (data.kind === 'file') {
          toast.success(`已摄入到${scope === 'global' ? '全局库' : '个人库'}`)
        } else {
          toast.success('整站抓取已开始,进度显示在列表上方')
        }
        onOpenChange(false)
        resetForm()
      },
      onError: (err: { message?: string }) =>
        toast.error(err?.message ?? '抓取失败'),
    })
  }

  const scopeLabel = scope === 'global' ? '全局库' : '个人库'
  const scopeDesc =
    scope === 'global'
      ? '内容将免审直接进入全局库,全员可检索'
      : '内容将进入你的个人库,仅本人可检索'

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Globe className="size-4" />
            抓取网页到{scopeLabel}
          </DialogTitle>
          <DialogDescription>{scopeDesc}</DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-2">
          {/* URL 输入 */}
          <div className="space-y-1.5">
            <Label htmlFor="ingest-url">网页地址</Label>
            <Input
              id="ingest-url"
              type="url"
              placeholder="https://example.com/patent"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              autoFocus
            />
          </div>

          {/* mode 切换 */}
          <div className="space-y-1.5">
            <Label>抓取范围</Label>
            <Tabs value={mode} onValueChange={(v) => setMode(v as 'scrape' | 'crawl')}>
              <TabsList className="grid w-full grid-cols-2">
                <TabsTrigger value="scrape">单页</TabsTrigger>
                <TabsTrigger value="crawl">整站</TabsTrigger>
              </TabsList>
            </Tabs>
            {mode === 'crawl' && (
              <p className="text-xs text-muted-foreground">
                整站抓取会爬取该 URL 下的多个页面,耗时较长(可能数分钟)
              </p>
            )}
          </div>

          {/* 高级选项(仅 crawl)*/}
          {mode === 'crawl' && (
            <Collapsible trigger="高级选项">
              <div className="space-y-1.5">
                <Label htmlFor="max-pages">最大页数 (1-100)</Label>
                <Input
                  id="max-pages"
                  type="number"
                  min={1}
                  max={100}
                  value={maxPages}
                  onChange={(e) => setMaxPages(Number(e.target.value) || 50)}
                />
                <p className="text-xs text-muted-foreground">
                  默认 50 页,上限 100 页(防止失控)
                </p>
              </div>
            </Collapsible>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button
            onClick={handleIngest}
            disabled={!url.trim() || ingest.isPending}
          >
            {ingest.isPending ? '抓取中...' : '开始抓取'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
```

**设计说明**:
- scope 参数化:`scopeLabel` / `scopeDesc` 根据 scope 切换文案
- scrape/crawl 用 Tabs 切换,crawl 才显示高级选项 Collapsible
- 提交后:scrape toast「已摄入」+ 关闭;crawl toast「已开始」+ 关闭(进度走 IngestJobTracker)
- resetForm 在关闭后清空表单

- [ ] **Step 2: 确认 Dialog 组件的导出**

Run: `grep -n "DialogDescription\|DialogFooter\|DialogHeader\|DialogTitle\|DialogContent" src/components/ui/dialog.tsx | head -10`
Expected: 这些命名导出都存在(标准 shadcn dialog)

- [ ] **Step 3: 类型检查**

Run: `cd apps/web && pnpm exec tsc --noEmit 2>&1 | grep -i "web-ingest-dialog" | head -5`
Expected: 无错误

- [ ] **Step 4: Commit**

```bash
cd "G:\03-Personal-Projects\TianGong"
git add apps/web/src/components/web-ingest-dialog.tsx
git commit -m "feat(web): WebIngestDialog 组件(scope 参数化)"
```

---

## Task 8: IngestJobCard 组件

**Files:**
- Create: `apps/web/src/components/ingest-job-card.tsx`

- [ ] **Step 1: 创建 ingest-job-card.tsx**

创建 `apps/web/src/components/ingest-job-card.tsx`:

```typescript
'use client'

import { CheckCircle, Loader2, X, XCircle } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Progress } from '@/components/ui/progress'
import type { WebIngestJob } from '@/types/api'

interface IngestJobCardProps {
  job: WebIngestJob
  onDismiss: () => void
}

export function IngestJobCard({ job, onDismiss }: IngestJobCardProps) {
  const isRunning = job.status === 'pending' || job.status === 'running'
  const isCompleted = job.status === 'completed'
  const isFailed = job.status === 'failed'

  // 进度:crawl 用 pages_fetched / max_pages
  const progress =
    job.mode === 'crawl' && job.pages_fetched > 0
      ? Math.min(100, (job.pages_fetched / Math.max(1, job.max_pages ?? 50)) * 100)
      : 0

  return (
    <Card className="apple-lift">
      <CardContent className="flex items-center gap-3 p-4">
        {/* 状态图标 */}
        <div className="shrink-0">
          {isRunning && (
            <Loader2 className="size-4 animate-spin text-muted-foreground" />
          )}
          {isCompleted && <CheckCircle className="size-4 text-success" />}
          {isFailed && <XCircle className="size-4 text-destructive" />}
        </div>

        {/* 内容 */}
        <div className="min-w-0 flex-1">
          <div className="flex items-center justify-between gap-2">
            <a
              href={job.url}
              target="_blank"
              rel="noopener noreferrer"
              className="truncate text-sm font-medium hover:underline"
              title={job.url}
            >
              {job.url}
            </a>
            <Badge variant="outline" className="shrink-0 text-[10px] font-normal">
              {job.mode === 'crawl' ? '整站' : '单页'}
            </Badge>
          </div>

          {/* 进度条(crawl 才展示)*/}
          {job.mode === 'crawl' && (
            <div className="mt-2 flex items-center gap-2">
              <Progress value={progress} className="h-1.5 flex-1" />
              <span className="shrink-0 text-[11px] tabular-nums text-muted-foreground">
                {job.pages_fetched}
                {isCompleted && job.pages_filtered > 0 && `/${job.pages_fetched + job.pages_filtered}`}
                {' 页'}
              </span>
            </div>
          )}

          {/* 错误信息 */}
          {isFailed && job.error_message && (
            <p
              className="mt-1 truncate text-xs text-destructive"
              title={job.error_message}
            >
              {job.error_message}
            </p>
          )}

          {/* 完成统计 */}
          {isCompleted && job.mode === 'crawl' && (
            <p className="mt-1 text-[11px] text-muted-foreground">
              抓取 {job.pages_fetched} 页
              {job.pages_filtered > 0 && `,过滤 ${job.pages_filtered} 页`}
              ,入库 {job.file_ids.length} 个文件
            </p>
          )}
        </div>

        {/* 关闭按钮(仅终态)*/}
        {!isRunning && (
          <Button variant="ghost" size="xs" onClick={onDismiss}>
            <X className="size-3.5" />
          </Button>
        )}
      </CardContent>
    </Card>
  )
}
```

**设计说明**:
- 三态图标:running 旋转 / completed 绿 / failed 红
- URL 是链接(可点开看原页面)
- 进度条仅在 crawl 模式展示,scrape 同步不经过任务卡片
- 完成后显示「抓取 N 页,过滤 M 页,入库 K 个文件」
- 终态可 dismiss(点 ×)

- [ ] **Step 2: 确认 Button 的 size="xs" 变体存在**

Run: `grep -n "xs:" src/components/ui/button.tsx | head -3`
Expected: 有输出(button 有 xs size,现有 KnowledgeFileCard 用了)

- [ ] **Step 3: 类型检查**

Run: `cd apps/web && pnpm exec tsc --noEmit 2>&1 | grep -i "ingest-job-card" | head -5`
Expected: 无错误

- [ ] **Step 4: Commit**

```bash
cd "G:\03-Personal-Projects\TianGong"
git add apps/web/src/components/ingest-job-card.tsx
git commit -m "feat(web): IngestJobCard 组件(进度条+状态)"
```

---

## Task 9: IngestJobTracker 组件

**Files:**
- Create: `apps/web/src/components/ingest-job-tracker.tsx`

- [ ] **Step 1: 创建 ingest-job-tracker.tsx**

创建 `apps/web/src/components/ingest-job-tracker.tsx`:

```typescript
'use client'

import { useState } from 'react'

import { IngestJobCard } from '@/components/ingest-job-card'
import { useIngestJobs } from '@/lib/queries'

interface IngestJobTrackerProps {
  scope: 'personal' | 'global'
}

/**
 * 任务追踪区:展示匹配 scope 的网页摄入任务。
 *
 * - 无任务时 return null(不占空间)
 * - 终态(completed/failed)任务可 dismiss
 * - 最多展示 5 个(防刷屏)
 * - 通过 useIngestJobs 的 refetchInterval 自动轮询(5s)
 */
export function IngestJobTracker({ scope }: IngestJobTrackerProps) {
  const { data: jobs } = useIngestJobs()
  const [dismissed, setDismissed] = useState<Set<string>>(new Set())

  const visible = (jobs ?? [])
    .filter((j) => j.scope === scope)
    .filter((j) => !dismissed.has(j.id))
    .slice(0, 5)

  if (visible.length === 0) return null

  function handleDismiss(jobId: string) {
    setDismissed((prev) => new Set(prev).add(jobId))
  }

  return (
    <div className="mb-4 space-y-2">
      {visible.map((job) => (
        <IngestJobCard
          key={job.id}
          job={job}
          onDismiss={() => handleDismiss(job.id)}
        />
      ))}
    </div>
  )
}
```

**设计说明**:
- 按 scope 过滤(用户端只看 personal,admin 端只看 global)
- dismissed 用 Set 记已关闭的 job id(本地 state,刷新后重置——可接受,因为完成的 job 用户已知晓)
- 最多 5 个(slice 0-5),避免大量历史任务刷屏
- 无任务 return null,不占布局空间

- [ ] **Step 2: 类型检查**

Run: `cd apps/web && pnpm exec tsc --noEmit 2>&1 | grep -i "ingest-job-tracker" | head -5`
Expected: 无错误

- [ ] **Step 3: Commit**

```bash
cd "G:\03-Personal-Projects\TianGong"
git add apps/web/src/components/ingest-job-tracker.tsx
git commit -m "feat(web): IngestJobTracker 任务追踪区(scope 过滤)"
```

---

## Task 10: 用户端 `/knowledge` 集成

**Files:**
- Modify: `apps/web/src/components/knowledge-manager.tsx`

- [ ] **Step 1: 加 import**

打开 `apps/web/src/components/knowledge-manager.tsx`,在文件顶部 import 区(第 1-19 行)加:

```typescript
import { useState } from 'react'  // 如果 useState 已 import,跳过这行(第 3 行已有)
```

修改第 4 行的 lucide import,加 `Globe`:
```typescript
import { Download, Globe, Send, Upload } from 'lucide-react'
```

在现有 import 之后加新组件 import:
```typescript
import { IngestJobTracker } from '@/components/ingest-job-tracker'
import { WebIngestDialog } from '@/components/web-ingest-dialog'
import { sourceTypeLabel } from '@/lib/source-type-labels'
```

- [ ] **Step 2: KnowledgeFileCard 的 Badge 用 label 映射**

找到 `KnowledgeFileCard` 组件(第 27-78 行),把第 49 行的 Badge 内容从:
```typescript
            {kf.source_type}
```
改为:
```typescript
            {sourceTypeLabel(kf.source_type)}
```

- [ ] **Step 3: KnowledgeManager 加 Dialog 状态 + 抓取按钮 + Tracker**

找到 `KnowledgeManager` 组件(第 80 行开始)。

第 81 行的 `useState` 后加 Dialog 状态:
```typescript
  const [tab, setTab] = useState<'personal' | 'global'>('personal')
  const [ingestOpen, setIngestOpen] = useState(false)  // 新增
  const fileRef = useRef<HTMLInputElement>(null)
```

找到 `PageHeader` 区(第 102-122 行),把 `{tab === 'personal' && (...)}` 块内的按钮区改成两个按钮并列:

```typescript
        {tab === 'personal' && (
          <div className="flex gap-2">
            <input
              ref={fileRef}
              type="file"
              accept=".pdf,.docx"
              onChange={handleUpload}
              className="hidden"
            />
            <Button
              onClick={() => fileRef.current?.click()}
              disabled={upload.isPending}
              className="gap-1.5"
            >
              <Upload className="size-3.5" />
              {upload.isPending ? '上传中...' : '上传素材'}
            </Button>
            {/* 新增:抓取网页 */}
            <Button
              variant="outline"
              onClick={() => setIngestOpen(true)}
              className="gap-1.5"
            >
              <Globe className="size-3.5" />
              抓取网页
            </Button>
          </div>
        )}
```

- [ ] **Step 4: 在 Tabs 上方插入 IngestJobTracker**

找到 `<div className="py-6">`(第 124 行),在它内部、`<Tabs>` 之前插入 Tracker:

```typescript
      <div className="py-6">
        {/* 新增:任务追踪区(无任务时不渲染)*/}
        <IngestJobTracker scope="personal" />

        <Tabs value={tab} onValueChange={(v) => setTab(v as 'personal' | 'global')}>
          ...
        </Tabs>
        ...
      </div>
```

- [ ] **Step 5: 在 PageShell 末尾加 WebIngestDialog**

找到 `</PageShell>`(第 155 行附近),在它之前加:

```typescript
      {/* 网页摄入 Dialog */}
      <WebIngestDialog
        scope="personal"
        open={ingestOpen}
        onOpenChange={setIngestOpen}
      />
    </PageShell>
```

- [ ] **Step 6: 类型检查 + build**

Run: `cd apps/web && pnpm exec tsc --noEmit 2>&1 | grep -i "knowledge-manager" | head -5`
Expected: 无错误

Run: `cd apps/web && pnpm build 2>&1 | tail -20`
Expected: build 成功(Next.js 编译通过)

- [ ] **Step 7: Commit**

```bash
cd "G:\03-Personal-Projects\TianGong"
git add apps/web/src/components/knowledge-manager.tsx
git commit -m "feat(web): /knowledge 加抓取网页入口 + 任务追踪 + source_type label"
```

---

## Task 11: admin 端 `/admin/content/knowledge` 集成

**Files:**
- Modify: `apps/web/src/app/(app)/admin/content/knowledge/page.tsx`

- [ ] **Step 1: 加 import**

打开 `apps/web/src/app/(app)/admin/content/knowledge/page.tsx`,在顶部 import 区加:

```typescript
import { useState } from 'react'  // 文件现有 import 是 { useRef },改成 { useRef, useState }
```

第 4 行 lucide import 加 `Globe`:
```typescript
import { Download, Globe, Upload } from 'lucide-react'
```

加新组件 import:
```typescript
import { IngestJobTracker } from '@/components/ingest-job-tracker'
import { WebIngestDialog } from '@/components/web-ingest-dialog'
import { sourceTypeLabel } from '@/lib/source-type-labels'
```

- [ ] **Step 2: GlobalKnowledgeCard 的 Badge 用 label 映射**

找到 `GlobalKnowledgeCard` 组件(第 87 行开始),把第 96 行的 Badge 内容从 `{kf.source_type}` 改为:
```typescript
            {sourceTypeLabel(kf.source_type)}
```

- [ ] **Step 3: AdminKnowledgePage 加 Dialog 状态 + 抓取按钮 + Tracker**

找到 `AdminKnowledgePage` 组件(第 27 行开始)。

第 28-29 行的 useRef 后加 useState:
```typescript
  const fileRef = useRef<HTMLInputElement>(null)
  const [ingestOpen, setIngestOpen] = useState(false)  // 新增
  const upload = useAdminUploadGlobal()
```

找到 `PageHeader`(第 48-64 行),把按钮区改成两个并列:

```typescript
      <PageHeader title="知识库直传" description={`全局库 · ${list.length} 个文件`}>
        <div className="flex gap-2">
          <input
            ref={fileRef}
            type="file"
            accept=".pdf,.docx"
            onChange={handleUpload}
            className="hidden"
          />
          <Button
            onClick={() => fileRef.current?.click()}
            disabled={upload.isPending}
            className="gap-1.5"
          >
            <Upload className="size-3.5" />
            {upload.isPending ? '上传中...' : '上传到全局库'}
          </Button>
          {/* 新增:抓取网页到全局库 */}
          <Button
            variant="outline"
            onClick={() => setIngestOpen(true)}
            className="gap-1.5"
          >
            <Globe className="size-3.5" />
            抓取网页
          </Button>
        </div>
      </PageHeader>
```

- [ ] **Step 4: 在列表上方插入 IngestJobTracker**

找到 `<div className="py-6">`(第 66 行),在它内部最前面加:

```typescript
      <div className="py-6">
        {/* 新增:任务追踪区(global scope)*/}
        <IngestJobTracker scope="global" />

        {isLoading ? (
          ...
        ) : list.length === 0 ? (
          ...
        ) : (
          ...
        )}
      </div>
```

- [ ] **Step 5: 在 PageShell 末尾加 WebIngestDialog**

找到 `</PageShell>`(第 83 行附近),在它之前加:

```typescript
      {/* 网页摄入 Dialog(scope=global,免审直入全局库)*/}
      <WebIngestDialog
        scope="global"
        open={ingestOpen}
        onOpenChange={setIngestOpen}
      />
    </PageShell>
```

- [ ] **Step 6: 类型检查 + build**

Run: `cd apps/web && pnpm exec tsc --noEmit 2>&1 | grep -iE "admin/content/knowledge" | head -5`
Expected: 无错误

Run: `cd apps/web && pnpm build 2>&1 | tail -20`
Expected: build 成功

- [ ] **Step 7: Commit**

```bash
cd "G:\03-Personal-Projects\TianGong"
git add "apps/web/src/app/(app)/admin/content/knowledge/page.tsx"
git commit -m "feat(web): /admin/content/knowledge 加抓取网页到全局库 + 任务追踪"
```

---

## Task 12: Firecrawl 配置页

**Files:**
- Create: `apps/web/src/app/(app)/admin/console/firecrawl/page.tsx`

- [ ] **Step 1: 创建目录 + 页面文件**

创建目录 `apps/web/src/app/(app)/admin/console/firecrawl/`,然后创建 `page.tsx`:

```typescript
'use client'

import { useEffect, useState } from 'react'
import { toast } from 'sonner'

import { PageHeader, PageShell } from '@/components/page-shell'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { useFirecrawlConfig, useSaveFirecrawlConfig } from '@/lib/queries'

/**
 * /admin/console/firecrawl — Firecrawl 全局配置页。
 *
 * 镜像 /admin/console/llm 但更简单(无 chat/embedding 拆分、无 model、无模板)。
 * 一个 enabled Switch 卡片 + api_key Input + base_url Input + 保存按钮。
 */
export default function FirecrawlConfigPage() {
  const { data, isLoading } = useFirecrawlConfig()
  const save = useSaveFirecrawlConfig()

  const [enabled, setEnabled] = useState(false)
  const [apiKey, setApiKey] = useState('')
  const [baseUrl, setBaseUrl] = useState('')

  // 首次加载用 query 数据填表单(用 useEffect,不在 render 里 setState)
  useEffect(() => {
    if (data) {
      setEnabled(data.enabled)
      setBaseUrl(data.base_url || '')
    }
  }, [data])

  function handleSave() {
    save.mutate(
      {
        enabled,
        api_key: apiKey, // 空串=不改
        base_url: baseUrl || null, // 空串当 null(不改)
      },
      {
        onSuccess: () => {
          toast.success('Firecrawl 配置已更新')
          setApiKey('') // 保存后清空 apiKey 输入
        },
        onError: (err: { message?: string }) =>
          toast.error(err?.message ?? '保存失败'),
      },
    )
  }

  if (isLoading) {
    return (
      <PageShell>
        <PageHeader title="Firecrawl 配置" description="网页摄入的 API 凭据" />
        <Skeleton className="h-64" />
      </PageShell>
    )
  }

  return (
    <PageShell>
      <PageHeader title="Firecrawl 配置" description="网页摄入的 API 凭据">
        <Button onClick={handleSave} disabled={save.isPending}>
          {save.isPending ? '保存中...' : '保存'}
        </Button>
      </PageHeader>

      <div className="space-y-4 py-6">
        {/* enabled 开关卡片 */}
        <div
          className="flex items-center justify-between rounded-2xl border border-black/[0.07] bg-card px-5 py-3.5 dark:border-white/10"
          style={{ boxShadow: 'var(--shadow-card)' }}
        >
          <div>
            <div className="text-sm font-medium">启用 Firecrawl</div>
            <div className="text-xs text-muted-foreground">
              {enabled ? '用户可使用网页摄入功能' : '关闭后用户无法抓取网页'}
            </div>
          </div>
          <Switch checked={enabled} onCheckedChange={setEnabled} />
        </div>

        {/* api_key 输入 */}
        <div className="space-y-2">
          <Label htmlFor="fc-api-key">API Key</Label>
          {data?.api_key_masked && (
            <p className="text-xs text-muted-foreground">
              当前:{data.api_key_masked}(留空不修改)
            </p>
          )}
          <Input
            id="fc-api-key"
            type="password"
            placeholder="留空不修改"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
          />
        </div>

        {/* base_url 输入 */}
        <div className="space-y-2">
          <Label htmlFor="fc-base-url">Base URL</Label>
          <Input
            id="fc-base-url"
            type="url"
            placeholder="https://api.firecrawl.dev"
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
          />
          <p className="text-xs text-muted-foreground">
            默认使用 Firecrawl 云服务,如需自部署可填自定义地址
          </p>
        </div>
      </div>
    </PageShell>
  )
}
```

**设计说明**:
- `useEffect` 填表单(避免 render 里 setState 的 React 警告)
- enabled 用独立 Switch 卡片(对齐 LLM 配置页风格)
- api_key 用 `type="password"`,展示当前脱敏值(`data.api_key_masked`)
- base_url 留空=不改(后端 null=不改)
- 保存后清空 apiKey 输入(避免重复提交)

- [ ] **Step 2: 类型检查 + build**

Run: `cd apps/web && pnpm exec tsc --noEmit 2>&1 | grep -i "firecrawl" | head -5`
Expected: 无错误

Run: `cd apps/web && pnpm build 2>&1 | tail -20`
Expected: build 成功

- [ ] **Step 3: Commit**

```bash
cd "G:\03-Personal-Projects\TianGong"
git add "apps/web/src/app/(app)/admin/console/firecrawl/page.tsx"
git commit -m "feat(web): Firecrawl 配置页(/admin/console/firecrawl)"
```

---

## Task 13: 控制台落地页改卡片网格

**Files:**
- Modify: `apps/web/src/app/(app)/admin/console/page.tsx`

- [ ] **Step 1: 读现有 console/page.tsx**

Run: `cat "apps/web/src/app/(app)/admin/console/page.tsx"`
Expected: 看到现有是 redirect 到 `/admin/console/llm`(约 6 行)

- [ ] **Step 2: 替换为卡片网格导航**

把 `apps/web/src/app/(app)/admin/console/page.tsx` 全文替换为:

```typescript
'use client'

import { BarChart3, FileText, Globe, Settings } from 'lucide-react'
import Link from 'next/link'

import { PageHeader, PageShell } from '@/components/page-shell'
import { Card, CardContent } from '@/components/ui/card'

const CONSOLE_SECTIONS = [
  {
    href: '/admin/console/llm',
    icon: Settings,
    title: 'LLM 配置',
    description: '全局对话与嵌入模型凭据',
  },
  {
    href: '/admin/console/firecrawl',
    icon: Globe,
    title: 'Firecrawl 配置',
    description: '网页摄入 API 凭据',
  },
  {
    href: '/admin/console/stats',
    icon: BarChart3,
    title: '调用统计',
    description: 'LLM 与 Firecrawl 用量',
  },
  {
    href: '/admin/console/audit',
    icon: FileText,
    title: '审计日志',
    description: '管理员操作记录',
  },
] as const

export default function ConsoleIndexPage() {
  return (
    <PageShell>
      <PageHeader title="控制台" description="系统配置与监控" />
      <div className="grid gap-4 py-6 sm:grid-cols-2">
        {CONSOLE_SECTIONS.map(({ href, icon: Icon, title, description }) => (
          <Link key={href} href={href}>
            <Card className="apple-lift transition-shadow hover:shadow-[var(--shadow-lift)]">
              <CardContent className="flex items-start gap-3 p-5">
                <div className="rounded-lg bg-muted p-2">
                  <Icon className="size-5" />
                </div>
                <div className="min-w-0">
                  <div className="text-sm font-medium">{title}</div>
                  <div className="mt-0.5 text-xs text-muted-foreground">
                    {description}
                  </div>
                </div>
              </CardContent>
            </Card>
          </Link>
        ))}
      </div>
    </PageShell>
  )
}
```

**设计说明**:
- 4 张卡片:LLM 配置 / Firecrawl 配置 / 调用统计 / 审计日志
- 每张卡片:图标(在 muted 背景圆角块里)+ 标题 + 描述
- `apple-lift` hover 抬升效果 + `hover:shadow-[var(--shadow-lift)]`
- 响应式 `sm:grid-cols-2`(2×2 网格)
- 删掉原 redirect(`redirect('/admin/console/llm')`)

**注意**:这改动现有行为——书签 `/admin/console` 不再自动跳 LLM,而是显示导航页。这是合理优化(提升发现性),spec 第 2 节已确认。

- [ ] **Step 3: 类型检查 + build**

Run: `cd apps/web && pnpm exec tsc --noEmit 2>&1 | grep -iE "admin/console/page" | head -5`
Expected: 无错误

Run: `cd apps/web && pnpm build 2>&1 | tail -20`
Expected: build 成功

- [ ] **Step 4: Commit**

```bash
cd "G:\03-Personal-Projects\TianGong"
git add "apps/web/src/app/(app)/admin/console/page.tsx"
git commit -m "feat(web): 控制台落地页改卡片网格导航"
```

---

## 完成验证(全部任务做完后)

- [ ] **Step 1: 全量类型检查 + build**

Run: `cd apps/web && pnpm exec tsc --noEmit`
Expected: 无新增类型错误(可能有既有的,只要不是本 feature 引入)

Run: `cd apps/web && pnpm build`
Expected: build 成功(Next.js 编译通过)

- [ ] **Step 2: 后端测试零回归**

Run: `cd apps/api && uv run pytest`
Expected: 全部通过(_file_out 加字段不破坏)

- [ ] **Step 3: 手动验证清单**

启动前后端(两个终端):
```bash
# 终端 1
cd apps/api && uv run uvicorn app.main:app --reload
# 终端 2
cd apps/web && pnpm dev
```

浏览器访问 `http://localhost:3000`,按 spec 第 8 节清单验证:

**用户端**(`/knowledge`,用普通用户登录):
- [ ] personal tab 看到「抓取网页」按钮(在「上传素材」旁)
- [ ] global tab **不**显示「抓取网页」按钮(用户端只能 personal)
- [ ] 点「抓取网页」→ Dialog 弹出 → 填 URL → 选单页 → 提交
- [ ] (需 admin 先配 Firecrawl key)toast「已摄入到个人库」+ 列表刷新出现「网页」Badge 的文件
- [ ] 选整站 → 展开高级选项调 max_pages → 提交 → toast「已开始抓取」+ 顶部出现任务卡片
- [ ] 任务卡片显示进度条 + 页数,完成后变绿 + 显示「抓取 N 页,入库 M 个文件」

**admin 端**(用 admin 登录):
- [ ] `/admin/console` 显示 4 张卡片(不再是 redirect)
- [ ] 点 Firecrawl 卡片 → 进配置页
- [ ] 填 api_key + 启用 + 保存 → toast「已更新」
- [ ] 重新进配置页,api_key 显示脱敏值
- [ ] `/admin/content/knowledge` 看到「抓取网页」按钮
- [ ] 抓取 scope=global → 进全局库(免审,文件 Badge 显示「网页」)

**source_type label**:
- [ ] 网页摄入文件 Badge 显示「网页」(不是 external_web)
- [ ] 既有 docx/pdf 文件 Badge 显示「Word」/「PDF」(不是 external_docx/external_pdf)

- [ ] **Step 4: 验收清单对照 spec**

逐项对照 spec 第 9 节验收标准(9 项)。

---

## 实施笔记(给执行 agent)

1. **前端无 vitest**:天工前端目前没有配置 vitest(spec 第 8 节确认)。所以不走严格 TDD,走「实现 + `pnpm build` 类型检查 + 手动验证」。每个 Task 的验证步骤是 `tsc --noEmit` + 关键 Task 加 `pnpm build`。

2. **`import('@/types/api').XXX` 内联类型**:api.ts 和 queries.ts 里用内联 import(对齐现有 `listPersonalKnowledge` 写法),不在文件顶部加 import。这是项目既有风格,保持一致。

3. **`(app)` 路由组的路径**:Next.js 路由组 `(app)` 在路径里不体现,但文件路径要带括号。bash 命令操作这些路径时要加引号:`git add "apps/web/src/app/(app)/admin/..."`。

4. **`apple-lift` / `var(--shadow-card)`**:这些是 globals.css 已定义的 Apple Liquid Glass 风格类/变量,直接用。不要自创阴影。

5. **Dialog 组件命名导出**:确认 `Dialog` / `DialogContent` / `DialogHeader` / `DialogTitle` / `DialogDescription` / `DialogFooter` 都从 `@/components/ui/dialog` 命名导出(标准 shadcn dialog)。Task 7 Step 2 会验证。

6. **`size` 变体**:`Button` 有 `xs` / `sm` / `default` / `lg` size(Task 8 Step 2 验证)。`Badge` 有 `default` / `outline` / `secondary` / `destructive` variant。

7. **Task 0 是后端改动**:虽然本 plan 主要是前端,但 Task 0 改的是 `apps/api/`(后端 `_file_out` 加 url)。这是前端的前置依赖(前端 KnowledgeFile.url 需要后端返回),必须先做。

8. **firecrawl v2 SDK 状态值**:后端用 `scraping`(进行中)/ `completed` / `failed`(Task 11 后端探查确认)。前端类型 `WebIngestJob.status` 已对齐(`'pending' | 'running' | 'completed' | 'failed'`)——注意后端 pending/running 都映射到前端「进行中」,前端用 `status === 'pending' || status === 'running'` 判断。

9. **Task 13 破坏现有 redirect**:控制台落地页从 redirect 改卡片网格,会让书签 `/admin/console` 看到导航页而非跳 LLM。spec 第 2/6 节已确认这是合理优化。
