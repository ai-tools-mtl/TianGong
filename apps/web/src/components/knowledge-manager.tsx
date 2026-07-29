'use client'

import { useRef, useState } from 'react'
import { Download, Globe, Send, Upload } from 'lucide-react'
import { toast } from 'sonner'

import { PageHeader, PageShell } from '@/components/page-shell'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { KnowledgeFileStatus } from '@/components/knowledge-file-status'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { api } from '@/lib/api'
import {
  useGlobalKnowledge,
  usePersonalKnowledge,
  useSubmitKnowledgeReview,
  useUploadKnowledgeFile,
} from '@/lib/queries'
import type { KnowledgeFile } from '@/types/api'
import { IngestJobTracker } from '@/components/ingest-job-tracker'
import { WebIngestDialog } from '@/components/web-ingest-dialog'
import { sourceTypeLabel } from '@/lib/source-type-labels'

function _formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function KnowledgeFileCard({
  kf,
  showSubmit,
}: {
  kf: KnowledgeFile
  showSubmit: boolean
}) {
  const submit = useSubmitKnowledgeReview()

  function handleSubmit() {
    submit.mutate(kf.id, {
      onSuccess: () => toast.success('已提交审核,等待管理员处理'),
      onError: () => toast.error('提交失败'),
    })
  }

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center justify-between gap-2 text-[15px]">
          <span className="truncate" title={kf.filename}>{kf.filename}</span>
          <Badge variant="outline" className="shrink-0 text-[10px] font-normal">
            {sourceTypeLabel(kf.source_type)}
          </Badge>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        <div className="flex items-center justify-between text-[11px] text-muted-foreground">
          <span>{_formatSize(kf.size)}</span>
          <span>{new Date(kf.created_at).toLocaleDateString('zh-CN')}</span>
        </div>
        <KnowledgeFileStatus kf={kf} />
        <div className="flex items-center gap-2 pt-1">
          <Button
            variant="ghost" size="xs" asChild
          >
            <a href={api.knowledgeFileUrl(kf.id)} download>
              <Download className="mr-1 size-3.5" /> 下载
            </a>
          </Button>
          {showSubmit && (
            <Button
              variant="ghost" size="xs"
              onClick={handleSubmit} disabled={submit.isPending}
            >
              <Send className="mr-1 size-3.5" /> 上报审核
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  )
}

export function KnowledgeManager() {
  const [tab, setTab] = useState<'personal' | 'global'>('personal')
  const [ingestOpen, setIngestOpen] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)
  const upload = useUploadKnowledgeFile()
  const { data: personalFiles, isLoading: personalLoading } = usePersonalKnowledge()
  const { data: globalFiles, isLoading: globalLoading } = useGlobalKnowledge()

  async function handleUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    upload.mutate(file, {
      onSuccess: () => toast.success('已上传，正在向量化（可在列表查看进度）'),
      onError: (err) => toast.error((err as { message?: string })?.message ?? '上传失败'),
    })
    if (fileRef.current) fileRef.current.value = ''
  }

  const files = tab === 'personal' ? (personalFiles ?? []) : (globalFiles ?? [])
  const loading = tab === 'personal' ? personalLoading : globalLoading

  return (
    <PageShell>
      <PageHeader title="知识库" description="管理可检索的参考素材与归档案例">
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
      </PageHeader>

      <div className="py-6">
        <IngestJobTracker scope="personal" />

        <Tabs value={tab} onValueChange={(v) => setTab(v as 'personal' | 'global')}>
          <TabsList>
            <TabsTrigger value="personal">个人库</TabsTrigger>
            <TabsTrigger value="global">全局共享库</TabsTrigger>
          </TabsList>
        </Tabs>

        <div className="mt-4">
          {loading ? (
            <p className="text-sm text-muted-foreground">加载中...</p>
          ) : files.length === 0 ? (
            <div
              className="rounded-2xl border border-black/[0.07] bg-card p-12 text-center text-sm text-muted-foreground dark:border-white/10"
              style={{ boxShadow: 'var(--shadow-card)' }}
            >
              {tab === 'personal'
                ? '个人库为空,上传 docx/pdf 素材开始'
                : '全局库暂无共享内容'}
            </div>
          ) : (
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {files.map((kf: KnowledgeFile) => (
                <KnowledgeFileCard
                  key={kf.id} kf={kf} showSubmit={tab === 'personal'}
                />
              ))}
            </div>
          )}
        </div>
      </div>

      <WebIngestDialog
        scope="personal"
        open={ingestOpen}
        onOpenChange={setIngestOpen}
      />
    </PageShell>
  )
}
