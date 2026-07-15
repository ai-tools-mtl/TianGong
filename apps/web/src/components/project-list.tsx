'use client'

import { useMemo, useState } from 'react'
import { Search } from 'lucide-react'

import { CreateProjectDialog } from '@/components/create-project-dialog'
import { PageHeader, PageShell } from '@/components/page-shell'
import { ProjectCard } from '@/components/project-card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useProjects, useTags } from '@/lib/queries'
import type { Project, Tag } from '@/types/api'

const STATUS_TABS = [
  { value: 'all', label: '全部' },
  { value: 'draft', label: '草稿' },
  { value: 'in_progress', label: '进行中' },
  { value: 'completed', label: '已完成' },
  { value: 'archived', label: '已归档' },
]

export function ProjectList() {
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('all')
  const [tagFilter, setTagFilter] = useState<string | null>(null)

  // 当筛选"已归档"时，需带 status 参数请求（后端默认排除 archived）
  const { data: rawProjects, isLoading, isError } = useProjects(
    statusFilter === 'archived' ? 'archived' : undefined,
  )
  const { data: allTags } = useTags()
  const projects: Project[] = rawProjects ?? []

  // 前端二次筛选（后端已支持参数，但为保持 debounce 简单这里前端筛）
  const filtered = useMemo(() => {
    let result = projects
    if (statusFilter !== 'all') {
      result = result.filter((p) => p.status === statusFilter)
    }
    if (tagFilter) {
      result = result.filter((p) => (p.tags ?? []).includes(tagFilter))
    }
    if (search.trim()) {
      const q = search.trim().toLowerCase()
      result = result.filter((p) => p.title.toLowerCase().includes(q))
    }
    return result
  }, [projects, statusFilter, tagFilter, search])

  return (
    <PageShell>
      <PageHeader title="我的项目" description="管理你的专利交底书">
        <CreateProjectDialog />
      </PageHeader>

      <div className="space-y-4 py-6">
        {/* 搜索框 */}
        <div className="relative max-w-md">
          <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="搜索项目标题..."
            className="pl-9"
          />
        </div>

        {/* 状态 Tabs */}
        <Tabs value={statusFilter} onValueChange={setStatusFilter}>
          <TabsList>
            {STATUS_TABS.map((tab) => (
              <TabsTrigger key={tab.value} value={tab.value}>
                {tab.label}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>

        {/* 标签筛选（仅有标签时显示） */}
        {allTags && allTags.length > 0 && (
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs text-muted-foreground">标签：</span>
            <Button
              variant={tagFilter === null ? 'secondary' : 'ghost'}
              size="xs"
              onClick={() => setTagFilter(null)}
            >
              全部
            </Button>
            {allTags.map((tag: Tag) => (
              <Badge
                key={tag.id}
                variant={tagFilter === tag.id ? 'default' : 'outline'}
                className="cursor-pointer select-none"
                onClick={() => setTagFilter(tagFilter === tag.id ? null : tag.id)}
              >
                {tag.name}
              </Badge>
            ))}
          </div>
        )}

        {/* 项目网格 */}
        {isLoading ? (
          <p className="text-sm text-muted-foreground">加载中...</p>
        ) : isError ? (
          <p className="text-sm text-destructive">加载失败，请重试</p>
        ) : filtered.length === 0 ? (
          <div className="rounded-lg border border-dashed p-12 text-center text-sm text-muted-foreground">
            {projects.length === 0
              ? '还没有项目，点击右上角「新建项目」开始你的第一份交底书'
              : '没有符合条件的项目'}
          </div>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {filtered.map((p) => (
              <ProjectCard key={p.id} project={p} />
            ))}
          </div>
        )}
      </div>
    </PageShell>
  )
}
