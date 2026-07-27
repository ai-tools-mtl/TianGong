# Firecrawl 网页摄入 — 前端设计文档

> 状态:Draft(v1.0,2026-07-27)
> 关联:后端 spec `docs/superpowers/specs/2026-07-27-firecrawl-web-ingestion-design.md`
> 设计契约:`docs/superpowers/specs/2026-07-14-ui-redesign-contract.md`(墨黑 + AI 紫 + Apple Liquid Glass)

---

## 1. 目标与范围

### 做什么

给天工前端加 Firecrawl 网页摄入的完整 UI,对接已实现的后端 API:

- **用户端**:在 `/knowledge` 页加「抓取网页」入口(scrape 单页/crawl 整站)+ crawl 任务进度追踪
- **admin 端**:在 `/admin/content/knowledge` 页加「抓取网页到全局库」入口(scope=global,免审直入)
- **admin 配置**:新建 `/admin/console/firecrawl` 页配 Firecrawl API key
- **控制台导航**:把 `/admin/console` 从 redirect 改为卡片网格导航

### 不做什么(YAGNI)

| 排除项 | 理由 |
|---|---|
| 知识库搜索 UI | 后端 `/knowledge/search` 已存在但前端一直未接,跟本 feature 解耦,独立做 |
| BYOK(用户自配 Firecrawl key) | 后端 spec 已排除(单用户大多没 Firecrawl 账号),前端不暴露 |
| crawl 实时 SSE 推送 | 后端是轮询模型(30s 间隔),前端用 react-query `refetchInterval` 对齐,不上 SSE |
| 移动端适配 | 设计契约明确 PC 端唯一目标(≥1280px) |
| LLMConfigEditPanel 复用 | Firecrawl 配置比 LLM 简单得多(无 chat/embedding 拆分、无 model、无模板),直接写 page 不复用重组件 |
| Progress 组件用第三方 | 手写 shadcn 风格(GOTCHAS F8:CLI 装不了组件,要手写) |

### 依赖

- **后端 feature 已完成**:分支 `feat/firecrawl-web-ingestion`,15 commits,682 tests passed
- 后端契约:`POST /api/v1/knowledge/ingest/web`、`GET /api/v1/knowledge/ingest/jobs/{id}`、`GET /api/v1/knowledge/ingest/jobs`、`GET/PUT /api/v1/admin/console/firecrawl`

### 前置后端小改(1 行)

`_file_out`(`apps/api/app/api/knowledge.py:68-78`)当前不返回 `url` 字段,但网页摄入的 `KnowledgeFile` 有 `url`(Task 3 加的列)。需补一行:

```python
def _file_out(kf: KnowledgeFile) -> dict:
    return {
        # ...现有字段
        "url": kf.url,  # 新增(网页来源才有值,其他为 None)
        "created_at": kf.created_at.isoformat(),
    }
```

这个改动作为本前端 spec 的 Task 0(前置),在前端任务开始前先补上,否则前端 `KnowledgeFile.url` 永远是 undefined。

---

## 2. 总体架构

### 模块分层

```
┌─────────────────────────────────────────────────────────────┐
│  页面层                                                       │
│  /knowledge (用户)            /admin/content/knowledge (admin)│
│  /admin/console/firecrawl    /admin/console (卡片导航)        │
└──────────────────┬──────────────────────────────────────────┘
                   │ 复用
┌──────────────────▼──────────────────────────────────────────┐
│  共享组件层(新建)                                             │
│  <WebIngestDialog scope=...>   URL 输入 + mode + 高级选项     │
│  <IngestJobTracker scope=...>  crawl 任务进度追踪              │
│  <IngestJobCard>               单个任务卡片(进度条 + 状态)    │
└──────────────────┬──────────────────────────────────────────┘
                   │
┌──────────────────▼──────────────────────────────────────────┐
│  数据层(扩展)                                                │
│  lib/api.ts       +ingestWeb/getIngestJob/listIngestJobs      │
│                   +getFirecrawlConfig/setFirecrawlConfig      │
│  lib/queries.ts   +useIngestWeb/useIngestJobs(轮询)           │
│                   +useFirecrawlConfig/useSaveFirecrawlConfig  │
│  types/api.ts     +WebIngestJob/WebIngestResult/FirecrawlSettings│
│                   +KnowledgeFile.url                          │
└─────────────────────────────────────────────────────────────┘
                   │
┌──────────────────▼──────────────────────────────────────────┐
│  基础组件层(新建)                                             │
│  ui/progress.tsx       进度条(轨道色 --track)               │
│  ui/collapsible.tsx    折叠组件(高级选项)                    │
└─────────────────────────────────────────────────────────────┘
```

### 关键设计决策

**① 共享组件 scope 参数化**:用户端(personal)和 admin 端(global)共用 `<WebIngestDialog>` 和 `<IngestJobTracker>`,通过 `scope` prop 区分。避免两套代码。

**② scrape 同步 / crawl 异步的 UI 分叉**:
- scrape:`useIngestWeb` mutation,`onSuccess` 直接 toast「已摄入」,列表自动刷新(react-query invalidate)。Dialog 关闭。
- crawl:`useIngestWeb` mutation 返回 job,Dialog 关闭 + toast「已开始抓取」,`<IngestJobTracker>` 用 `useIngestJobs`(带 `refetchInterval`)轮询直到 completed/failed。

**③ 任务追踪区按需显示**:`<IngestJobTracker>` 只在有 running/pending 任务时渲染,无任务时不占空间(避免空态噪音)。

**④ admin 控制台落地页改卡片网格**:从 redirect `/admin/console/llm` 改为 4 张卡片(LLM 配置 / Firecrawl / 调用统计 / 审计日志),提升发现性。**注意**:这改动现有 redirect 行为,书签会失效,但属于合理优化。

---

## 3. 数据层改动

### 3.1 types/api.ts 扩展

```typescript
// KnowledgeFile 加 url 字段(后端 Task 3 已加)
export interface KnowledgeFile {
  // ...现有字段
  url?: string | null  // 网页来源的原 URL(external_web 才有)
}

// 网页摄入任务(对应后端 WebIngestionJob)
export interface WebIngestJob {
  id: string
  url: string
  mode: 'scrape' | 'crawl'
  scope: 'personal' | 'global'
  status: 'pending' | 'running' | 'completed' | 'failed'
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

// 请求体
export interface WebIngestRequest {
  url: string
  mode: 'scrape' | 'crawl'
  scope: 'personal' | 'global'
  max_pages?: number  // 仅 crawl,默认 1
}

// Firecrawl 全局配置(GET /admin/console/firecrawl)
export interface FirecrawlSettings {
  enabled: boolean
  api_key_masked: string  // 脱敏,如 "fc-***xxxx"
  base_url: string
}

// PUT 请求体
export interface FirecrawlConfigPayload {
  enabled: boolean
  api_key: string         // 空串 = 不改
  base_url: string | null // null = 不改
}
```

### 3.2 lib/api.ts 扩展

在现有 `api` 对象的知识库段(`api.ts:508-564`)后追加:

```typescript
// 网页摄入
async ingestWeb(payload: WebIngestRequest): Promise<WebIngestResult> {
  return request('/api/v1/knowledge/ingest/web', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
},

async getIngestJob(jobId: string): Promise<WebIngestJob> {
  return request(`/api/v1/knowledge/ingest/jobs/${jobId}`)
},

async listIngestJobs(): Promise<WebIngestJob[]> {
  return request('/api/v1/knowledge/ingest/jobs')
},

// Firecrawl 全局配置(admin)
async getFirecrawlConfig(): Promise<FirecrawlSettings> {
  return request('/api/v1/admin/console/firecrawl')
},

async setFirecrawlConfig(payload: FirecrawlConfigPayload): Promise<{ ok: true }> {
  return request('/api/v1/admin/console/firecrawl', {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
},
```

**注意**:走 `request()` wrapper(自动加 `/api/v1` 前缀 + JSON Content-Type + 凭据),不用像 `uploadKnowledgeFile` 那样绕开(那个是因为 FormData)。

### 3.3 lib/queries.ts 扩展

#### queryKeys 扩展

```typescript
export const queryKeys = {
  // ...现有
  knowledgeJobs: ['knowledge', 'ingest-jobs'] as const,
  knowledgeJob: (id: string) => ['knowledge', 'ingest-jobs', id] as const,
  admin: {
    // ...现有 llmConfig
    firecrawlConfig: ['admin', 'firecrawl-config'] as const,
  },
}
```

#### 网页摄入 hooks

```typescript
// 发起摄入(scrape 同步 / crawl 异步)
export function useIngestWeb() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: WebIngestRequest) => api.ingestWeb(payload),
    onSuccess: (data) => {
      // crawl 任务需要轮询,scrape 直接刷文件列表
      queryClient.invalidateQueries({ queryKey: queryKeys.knowledgeJobs })
      if (data.kind === 'file') {
        // scrape:刷对应 scope 的文件列表
        queryClient.invalidateQueries({
          queryKey: data.file.scope === 'global'
            ? queryKeys.knowledgeGlobal
            : queryKeys.knowledgePersonal,
        })
      }
    },
  })
}

// 列出本人的摄入任务(带轮询,只有 running/pending 时才轮询)
export function useIngestJobs() {
  return useQuery({
    queryKey: queryKeys.knowledgeJobs,
    queryFn: () => api.listIngestJobs(),
    refetchInterval: (query) => {
      const jobs = query.state.data
      // 只要有进行中的任务,就 5s 轮询一次(前端轮询比后端 30s 更密,因为要更新 UI)
      const hasActive = jobs?.some(j => j.status === 'pending' || j.status === 'running')
      return hasActive ? 5000 : false
    },
  })
}
```

**关键约定**(对齐现有):hook 的 onSuccess 只 invalidate,不弹 toast。toast 由调用方组件处理。

#### Firecrawl 配置 hooks

```typescript
export function useFirecrawlConfig() {
  return useQuery({
    queryKey: queryKeys.admin.firecrawlConfig,
    queryFn: () => api.getFirecrawlConfig(),
  })
}

export function useSaveFirecrawlConfig() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: FirecrawlConfigPayload) => api.setFirecrawlConfig(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.admin.firecrawlConfig })
      // 失效审计缓存(对齐 useSaveGlobalLLM)
      queryClient.invalidateQueries({ queryKey: queryKeys.admin.auditLogs })
    },
  })
}
```

---

## 4. 基础组件(新建)

### 4.1 ui/progress.tsx(进度条)

shadcn/ui 风格进度条。**手写**(GOTCHAS F8:CLI 装不了组件)。

```typescript
'use client'

import { cn } from '@/lib/utils'

interface ProgressProps extends React.HTMLAttributes<HTMLDivElement> {
  value?: number  // 0-100
}

export const Progress = React.forwardRef<HTMLDivElement, ProgressProps>(
  ({ className, value = 0, ...props }, ref) => (
    <div
      ref={ref}
      className={cn(
        'h-2 w-full overflow-hidden rounded-full',
        className,
      )}
      style={{ background: 'var(--track)' }}
      {...props}
    >
      <div
        className="h-full rounded-full transition-all duration-300"
        style={{
          width: `${Math.min(100, Math.max(0, value))}%`,
          background: 'hsl(var(--primary))',
        }}
      />
    </div>
  ),
)
Progress.displayName = 'Progress'
```

**设计**:
- 轨道色用 `var(--track)`(已在 globals.css 定义 `#e8e8ed`)
- 填充色用 primary(墨黑),不用 AI 紫(进度条是产品态,不是 AI 元素)
- 圆角 `rounded-full`,高 8px(`h-2`)
- 过渡动画 `duration-300`(平滑)

### 4.2 ui/collapsible.tsx(折叠组件)

shadcn/ui 风格折叠。**手写**(用 `<details>` 原生元素最简,或用 Radix)。

**简化方案**:用原生 `<details>` + Tailwind 样式,避免引入 Radix 依赖:

```typescript
'use client'

import { ChevronDown } from 'lucide-react'
import { cn } from '@/lib/utils'

interface CollapsibleProps {
  trigger: React.ReactNode
  children: React.ReactNode
  className?: string
}

export function Collapsible({ trigger, children, className }: CollapsibleProps) {
  return (
    <details className={cn('group', className)}>
      <summary className="flex cursor-pointer list-none items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
        <ChevronDown className="size-3.5 transition-transform group-open:rotate-90" />
        {trigger}
      </summary>
      <div className="mt-2">{children}</div>
    </details>
  )
}
```

**设计**:用原生 `<details>` 最轻量,`group-open:rotate-90` 让箭头展开时旋转。

---

## 5. 共享业务组件

### 5.1 WebIngestDialog(URL 输入 + mode 选择)

**文件**:`apps/web/src/components/web-ingest-dialog.tsx`

**Props**:
```typescript
interface WebIngestDialogProps {
  scope: 'personal' | 'global'  // 决定入库目标 + Dialog 文案
  open: boolean
  onOpenChange: (open: boolean) => void
}
```

**结构**:
```
<Dialog>
  <DialogContent>
    <DialogHeader>
      <DialogTitle>
        {scope === 'global' ? '抓取网页到全局库' : '抓取网页到个人库'}
      </DialogTitle>
      <DialogDescription>
        {scope === 'global'
          ? '内容将免审直接进入全局库,全员可检索'
          : '内容将进入你的个人库,仅本人可检索'}
      </DialogDescription>
    </DialogHeader>

    {/* URL 输入 */}
    <div>
      <Label>网页地址</Label>
      <Input
        type="url"
        placeholder="https://example.com/patent"
        value={url}
        onChange={...}
      />
    </div>

    {/* mode 切换(单页/整站)*/}
    <Tabs value={mode} onValueChange={...}>
      <TabsList>
        <TabsTrigger value="scrape">单页</TabsTrigger>
        <TabsTrigger value="crawl">整站</TabsTrigger>
      </TabsList>
    </Tabs>
    {mode === 'crawl' && (
      <p className="text-xs text-muted-foreground">
        整站抓取会爬取该 URL 下的多个页面,耗时较长(可能数分钟)
      </p>
    )}

    {/* 高级选项(折叠,仅 crawl 时显示)*/}
    {mode === 'crawl' && (
      <Collapsible trigger="高级选项">
        <div>
          <Label>最大页数(1-100)</Label>
          <Input
            type="number"
            min={1}
            max={100}
            value={maxPages}
            onChange={...}
          />
          <p className="text-xs text-muted-foreground">默认 50 页</p>
        </div>
      </Collapsible>
    )}

    <DialogFooter>
      <Button variant="outline" onClick={close}>取消</Button>
      <Button
        onClick={handleIngest}
        disabled={!url || ingest.isPending}
      >
        {ingest.isPending ? '抓取中...' : '开始抓取'}
      </Button>
    </DialogFooter>
  </DialogContent>
</Dialog>
```

**handleIngest 逻辑**:
```typescript
function handleIngest() {
  ingest.mutate(
    { url, mode, scope, max_pages: mode === 'crawl' ? maxPages : 1 },
    {
      onSuccess: (data) => {
        if (data.kind === 'file') {
          toast.success('已摄入到' + (scope === 'global' ? '全局库' : '个人库'))
        } else {
          toast.success('整站抓取已开始,进度显示在列表上方')
        }
        onOpenChange(false)  // 关闭 Dialog
        resetForm()
      },
      onError: (err) => toast.error(err.message ?? '抓取失败'),
    },
  )
}
```

### 5.2 IngestJobTracker(任务追踪区)

**文件**:`apps/web/src/components/ingest-job-tracker.tsx`

**Props**:
```typescript
interface IngestJobTrackerProps {
  scope: 'personal' | 'global'  // 过滤展示哪个 scope 的任务
}
```

**结构**:
```typescript
export function IngestJobTracker({ scope }: IngestJobTrackerProps) {
  const { data: jobs } = useIngestJobs()

  // 只展示匹配 scope + 未完成的任务(completed/failed 短暂展示后自动消失)
  const [dismissed, setDismissed] = useState<Set<string>>(new Set())
  const visible = (jobs ?? [])
    .filter(j => j.scope === scope)
    .filter(j => !dismissed.has(j.id))
    .filter(j =>
      j.status === 'pending' ||
      j.status === 'running' ||
      (j.status === 'completed' && /* 5 分钟内 */) ||
      (j.status === 'failed' && /* 5 分钟内 */)
    )
    .slice(0, 5)  // 最多展示 5 个,避免刷屏

  if (visible.length === 0) return null  // 无任务不渲染

  return (
    <div className="mb-4 space-y-2">
      {visible.map(job => (
        <IngestJobCard
          key={job.id}
          job={job}
          onDismiss={() => setDismissed(prev => new Set(prev).add(job.id))}
        />
      ))}
    </div>
  )
}
```

**设计要点**:
- completed/failed 任务展示 5 分钟后可手动 dismiss(点 × 关闭),避免永久占屏
- 最多 5 个,超过的旧任务不展示(防刷屏)
- 无任务时 `return null`,不占任何空间

### 5.3 IngestJobCard(单个任务卡片)

**文件**:`apps/web/src/components/ingest-job-card.tsx`

**Props**:
```typescript
interface IngestJobCardProps {
  job: WebIngestJob
  onDismiss: () => void
}
```

**结构**:
```typescript
export function IngestJobCard({ job, onDismiss }: IngestJobCardProps) {
  const isRunning = job.status === 'pending' || job.status === 'running'
  const progress = job.mode === 'crawl' && job.max_pages
    ? Math.min(100, (job.pages_fetched / job.max_pages) * 100)
    : 0

  return (
    <Card className="apple-lift">
      <CardContent className="flex items-center gap-3 p-4">
        {/* 状态图标 */}
        <div className="shrink-0">
          {isRunning && <Loader2 className="size-4 animate-spin text-muted-foreground" />}
          {job.status === 'completed' && <CheckCircle className="size-4 text-success" />}
          {job.status === 'failed' && <XCircle className="size-4 text-destructive" />}
        </div>

        {/* 内容 */}
        <div className="min-w-0 flex-1">
          <div className="flex items-center justify-between gap-2">
            <span className="truncate text-sm font-medium" title={job.url}>
              {job.url}
            </span>
            <Badge variant="outline" className="shrink-0 text-[10px]">
              {job.mode === 'crawl' ? '整站' : '单页'}
            </Badge>
          </div>

          {/* 进度(crawl 才展示)*/}
          {job.mode === 'crawl' && (
            <div className="mt-2 flex items-center gap-2">
              <Progress value={progress} className="h-1.5 flex-1" />
              <span className="shrink-0 text-[11px] text-muted-foreground tabular-nums">
                {job.pages_fetched}
                {job.status === 'completed' && `/${job.pages_fetched} 页`}
                {job.status === 'failed' && ' 页'}
              </span>
            </div>
          )}

          {/* 错误信息 */}
          {job.status === 'failed' && job.error_message && (
            <p className="mt-1 truncate text-xs text-destructive" title={job.error_message}>
              {job.error_message}
            </p>
          )}

          {/* 完成统计 */}
          {job.status === 'completed' && job.mode === 'crawl' && (
            <p className="mt-1 text-[11px] text-muted-foreground">
              抓取 {job.pages_fetched} 页
              {job.pages_filtered > 0 && `,过滤 ${job.pages_filtered} 页`}
              ,入库 {job.file_ids.length} 个文件
            </p>
          )}
        </div>

        {/* 关闭按钮(仅 completed/failed)*/}
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

---

## 6. 页面集成

### 6.1 用户端:`/knowledge` 页

**文件**:`apps/web/src/components/knowledge-manager.tsx`

改动:
1. import `Globe` 图标 + `WebIngestDialog` + `IngestJobTracker`
2. `KnowledgeManager` 加 `useState` 控制 Dialog 开关
3. `PageHeader` 在「上传素材」按钮旁加「抓取网页」按钮(两个按钮都只在 personal tab 显示)
4. `Tabs` 上方插入 `<IngestJobTracker scope="personal" />`(无任务时不渲染)
5. `KnowledgeFileCard` 的 source_type Badge 加 label 映射(`external_web` → `网页`)

**关键改动点**:

```typescript
// PageHeader 改(第 103-121 行)
<PageHeader title="知识库" description="...">
  {tab === 'personal' && (
    <div className="flex gap-2">
      {/* 现有上传按钮 */}
      <Button onClick={() => fileRef.current?.click()} ...>
        <Upload className="size-3.5" />
        {upload.isPending ? '上传中...' : '上传素材'}
      </Button>
      {/* 新增:抓取网页 */}
      <Button variant="outline" onClick={() => setIngestOpen(true)} className="gap-1.5">
        <Globe className="size-3.5" />
        抓取网页
      </Button>
    </div>
  )}
</PageHeader>

{/* Tabs 上方插入任务追踪 */}
<IngestJobTracker scope="personal" />

<Tabs value={tab} ...>
  ...
</Tabs>

{/* Dialog(放在 PageShell 末尾)*/}
<WebIngestDialog
  scope="personal"
  open={ingestOpen}
  onOpenChange={setIngestOpen}
/>
```

**source_type label 映射**:
```typescript
const SOURCE_TYPE_LABELS: Record<string, string> = {
  external_pdf: 'PDF',
  external_docx: 'Word',
  external_web: '网页',
  disclosure_export: '归档',
}

// Badge 改
<Badge variant="outline" className="shrink-0 text-[10px] font-normal">
  {SOURCE_TYPE_LABELS[kf.source_type] ?? kf.source_type}
</Badge>
```

### 6.2 admin 端:`/admin/content/knowledge` 页

**文件**:`apps/web/src/app/(app)/admin/content/knowledge/page.tsx`

改动(对称用户端):
1. `PageHeader` 在「上传到全局库」按钮旁加「抓取网页」按钮
2. 列表上方插入 `<IngestJobTracker scope="global" />`
3. 页面末尾加 `<WebIngestDialog scope="global" ... />`
4. `GlobalKnowledgeCard` 的 Badge 也加 source_type label 映射(抽成共享常量)

### 6.3 admin 配置页:`/admin/console/firecrawl`(新建)

**文件**:`apps/web/src/app/(app)/admin/console/firecrawl/page.tsx`

**镜像 `/admin/console/llm/page.tsx` 但更简单**:

```typescript
'use client'

import { useEffect, useState } from 'react'
import { toast } from 'sonner'

import { PageHeader, PageShell } from '@/components/page-shell'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Skeleton } from '@/components/ui/skeleton'
import { useFirecrawlConfig, useSaveFirecrawlConfig } from '@/lib/queries'

export default function FirecrawlConfigPage() {
  const { data, isLoading } = useFirecrawlConfig()
  const save = useSaveFirecrawlConfig()

  const [enabled, setEnabled] = useState(false)
  const [apiKey, setApiKey] = useState('')  // 空串=不改
  const [baseUrl, setBaseUrl] = useState('')  // 空串=不改(简化,不用 None 三态)

  // 首次加载时用 query 数据填表单(用 useEffect,不要在 render 里 setState)
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
        api_key: apiKey,  // 空串=不改
        base_url: baseUrl || null,  // 空串当 null 处理(不改)
      },
      {
        onSuccess: () => {
          toast.success('Firecrawl 配置已更新')
          setApiKey('')  // 保存后清空 apiKey 输入(避免重复提交)
        },
        onError: (err) => toast.error(err.message ?? '保存失败'),
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
          <Label>API Key</Label>
          {data?.api_key_masked && (
            <p className="text-xs text-muted-foreground">
              当前:{data.api_key_masked}(留空不修改)
            </p>
          )}
          <Input
            type="password"
            placeholder="留空不修改"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
          />
        </div>

        {/* base_url 输入 */}
        <div className="space-y-2">
          <Label>Base URL</Label>
          <Input
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

**关键设计**:
- enabled Switch 用独立卡片(对齐 LLM 配置页的 `rounded-2xl border bg-card` 风格)
- api_key 用 `type="password"` 隐藏输入,`data.api_key_masked` 展示当前脱敏值
- base_url 输入框,留空=不改(后端 null=不改)
- 保存按钮在 PageHeader 右侧(对齐 LLM 页)

### 6.4 admin 控制台落地页:`/admin/console`(改)

**文件**:`apps/web/src/app/(app)/admin/console/page.tsx`

从 redirect 改为卡片网格导航:

```typescript
'use client'

import Link from 'next/link'
import { Settings, Globe, BarChart3, FileText } from 'lucide-react'

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
]

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
                <div>
                  <div className="text-sm font-medium">{title}</div>
                  <div className="mt-0.5 text-xs text-muted-foreground">{description}</div>
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

**注意**:删掉原来的 `redirect('/admin/console/llm')`,改为卡片网格。**这会让书签 `/admin/console` 的用户看到导航页而非直接跳 LLM**——是合理优化,提升发现性。

---

## 7. 错误处理

### 用户端错误

| 场景 | 处理 | 用户感知 |
|---|---|---|
| Firecrawl 未配置(admin 没配 key) | `useIngestWeb` onError | toast.error「Firecrawl 未配置,请联系管理员」 |
| URL 校验失败(SSRF/格式错) | 同上 | toast.error 显示后端具体原因 |
| scrape 抓取失败 | 同上 | toast.error「页面抓取失败」 |
| scrape 内容被质量过滤 | 同上 | toast.error「内容未通过质量过滤(可能为空白页/导航页/非中英文)」 |
| 配额不足 | 同上 | toast.error「今日配额已用尽」 |
| 非 admin 入 global | 同上 | toast.error「仅管理员可入全局库」(前端按钮也控制,但后端是权威) |
| crawl 远端失败 | IngestJobCard 展示 failed | 任务卡片红色 + error_message |
| 网络错 | 同上 | toast.error「网络错误」 |

### admin 配置错误

| 场景 | 处理 |
|---|---|
| api_key 无效(保存时不校验,用时才报) | 不在前端拦截,后端 scrape 时报「Firecrawl key 失效」|
| base_url 格式错 | Input type=url 浏览器原生校验 |

### loading 态

- Dialog 提交时按钮显示「抓取中...」+ disabled
- 配置页首次加载用 `<Skeleton>`
- 任务卡片 running 时 `Loader2` 旋转

---

## 8. 测试策略

前端测试策略:**优先手动验证 + 关键单元测试**。天工前端目前测试覆盖较少(主要是后端 pytest),前端不强行上 vitest(项目未配置)。

### 手动验证清单(实现后跑一遍)

**用户端**:
- [ ] `/knowledge` 页 personal tab 看到「抓取网页」按钮
- [ ] 点开 Dialog,填 URL,选单页,提交 → toast「已摄入到个人库」+ 列表刷新出现新文件
- [ ] 选整站,展开高级选项调 max_pages,提交 → toast「已开始抓取」+ 任务追踪区出现进行中卡片
- [ ] crawl 完成后任务卡片变绿 + 显示「抓取 N 页,入库 M 个文件」+ 列表刷新
- [ ] global tab 不显示「抓取网页」按钮(用户端只能 personal)

**admin 端**:
- [ ] `/admin/content/knowledge` 看到「抓取网页」按钮
- [ ] 抓取 scope=global → 进全局库(免审)
- [ ] 任务追踪区显示 global scope 的任务

**admin 配置**:
- [ ] `/admin/console` 显示 4 张卡片导航
- [ ] 点 Firecrawl 卡片进配置页
- [ ] 填 api_key + 启用 + 保存 → toast「已更新」
- [ ] 重新进配置页,api_key 显示脱敏值

**source_type label**:
- [ ] 网页摄入的文件 Badge 显示「网页」而非「external_web」

### 单元测试(可选,若项目后续加 vitest)

- `useIngestWeb` onSuccess 正确 invalidate(scrape 刷文件列表,crawl 刷 jobs)
- `useIngestJobs` refetchInterval 在有 active 任务时返回 5000,否则 false
- `IngestJobTracker` 按 scope 过滤
- `IngestJobCard` 进度计算(pages_fetched / max_pages)

---

## 9. 实施清单

### 新建文件(7 个)

| 文件 | 职责 |
|---|---|
| `apps/web/src/components/ui/progress.tsx` | 进度条基础组件 |
| `apps/web/src/components/ui/collapsible.tsx` | 折叠组件(高级选项) |
| `apps/web/src/components/web-ingest-dialog.tsx` | URL 输入 + mode 选择 Dialog |
| `apps/web/src/components/ingest-job-tracker.tsx` | 任务追踪区(按 scope 过滤) |
| `apps/web/src/components/ingest-job-card.tsx` | 单个任务卡片(进度条 + 状态) |
| `apps/web/src/app/(app)/admin/console/firecrawl/page.tsx` | Firecrawl 配置页 |
| `apps/web/src/lib/source-type-labels.ts` | source_type label 映射常量(共享) |

### 改动文件(5 个)

| 文件 | 改动 |
|---|---|
| `apps/web/src/types/api.ts` | 加 WebIngestJob/WebIngestResult/FirecrawlSettings/KnowledgeFile.url |
| `apps/web/src/lib/api.ts` | 加 ingestWeb/getIngestJob/listIngestJobs/getFirecrawlConfig/setFirecrawlConfig |
| `apps/web/src/lib/queries.ts` | 加 useIngestWeb/useIngestJobs/useFirecrawlConfig/useSaveFirecrawlConfig + queryKeys |
| `apps/web/src/components/knowledge-manager.tsx` | 加抓取按钮 + IngestJobTracker + source_type label |
| `apps/web/src/app/(app)/admin/content/knowledge/page.tsx` | 加抓取按钮 + IngestJobTracker + source_type label |
| `apps/web/src/app/(app)/admin/console/page.tsx` | redirect 改卡片网格 |

### 验收标准

1. ✅ 用户可在 `/knowledge` personal tab 抓取网页(scrape 同步 + crawl 异步)
2. ✅ crawl 进度在列表上方实时展示(5s 轮询)
3. ✅ admin 可在 `/admin/content/knowledge` 抓取到全局库
4. ✅ admin 可在 `/admin/console/firecrawl` 配置 API key
5. ✅ `/admin/console` 显示卡片导航(含 Firecrawl 入口)
6. ✅ source_type 显示中文 label(网页/PDF/Word/归档)
7. ✅ SSRF/配额/未配置等错误有清晰 toast 提示
8. ✅ 现有 docx/pdf 上传 + 审核流零回归
9. ✅ `pnpm build` 通过(类型检查 + 编译)

---

## 附录 A:与后端 API 的契约对齐

| 前端调用 | 后端端点 | 后端文件:行 |
|---|---|---|
| `api.ingestWeb(payload)` | `POST /knowledge/ingest/web` | `apps/api/app/api/knowledge.py:181` |
| `api.getIngestJob(id)` | `GET /knowledge/ingest/jobs/{id}` | `apps/api/app/api/knowledge.py:202` |
| `api.listIngestJobs()` | `GET /knowledge/ingest/jobs` | `apps/api/app/api/knowledge.py:213` |
| `api.getFirecrawlConfig()` | `GET /admin/console/firecrawl` | `apps/api/app/api/admin/console.py:265` |
| `api.setFirecrawlConfig(payload)` | `PUT /admin/console/firecrawl` | `apps/api/app/api/admin/console.py:276` |

**响应结构对照**:
- `ingestWeb` 返回联合类型 `{kind:'file',file}` 或 `{kind:'job',job}`(后端 `_job_out` + `_file_out`)
- `getFirecrawlConfig` 返回 `{enabled, api_key_masked, base_url}`(后端 `get_firecrawl_settings`)
- `setFirecrawlConfig` 请求体 `{enabled, api_key, base_url}`,api_key 空串=不改,base_url null=不改

## 附录 B:设计契约对齐检查

| 设计契约要求 | 本设计如何遵守 |
|---|---|
| 墨黑为主,紫色只服务 AI | 进度条/按钮/卡片全用墨黑 + muted,**网页摄入不是 AI 元素不用紫** |
| Apple Liquid Glass(11px 圆角 + 双层柔影) | 卡片用 `rounded-2xl` + `var(--shadow-card)` + `apple-lift` |
| PC 端 ≥1280px | 不做移动端适配,响应式 grid `sm:grid-cols-2 lg:grid-cols-3` |
| shadcn/ui 风格 | 复用现有 Button/Card/Input/Switch/Tabs/Dialog/Badge |
| 思源黑体只挂 prose | UI 文案用系统栈,不挂 `--font-zh` |
| 上传参考 figure-upload 模式 | 抓取网页按钮对齐「上传素材」按钮的 PageHeader 放置 |
| hook onSuccess 只 invalidate 不 toast | `useIngestWeb`/`useSaveFirecrawlConfig` 都遵守,toast 在组件弹 |
