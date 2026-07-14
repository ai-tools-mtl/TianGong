'use client'

import { Upload } from 'lucide-react'
import { useRef, useState } from 'react'
import { toast } from 'sonner'

import { PageHeader, PageShell } from '@/components/page-shell'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { api } from '@/lib/api'
import { useTemplates } from '@/lib/queries'
import type { TemplateSummary } from '@/types/api'

const POLL_INTERVAL_MS = 1500
const POLL_MAX_ATTEMPTS = 40 // 60s 上限

async function pollParseJob(jobId: string): Promise<'completed' | 'failed'> {
  for (let i = 0; i < POLL_MAX_ATTEMPTS; i++) {
    const job = await api.getParseJob(jobId)
    if (job.status === 'completed') return 'completed'
    if (job.status === 'failed') return 'failed'
    await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS))
  }
  return 'failed'
}

export function TemplateManager() {
  const { data, isLoading, refetch } = useTemplates()
  const templates: TemplateSummary[] = data ?? []
  const fileRef = useRef<HTMLInputElement>(null)
  const [uploading, setUploading] = useState(false)

  async function handleUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    setUploading(true)
    try {
      const { parse_job_id } = await api.uploadTemplate(file)
      toast.info('模板已上传，正在解析...')
      const result = await pollParseJob(parse_job_id)
      if (result === 'completed') {
        toast.success('模板解析成功')
        refetch()
      } else {
        toast.error('模板解析失败')
      }
    } catch {
      toast.error('上传失败')
    } finally {
      setUploading(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  return (
    <PageShell>
      <PageHeader title="模板管理" description="上传 Word 模板定义交底书章节结构">
        <input
          ref={fileRef}
          type="file"
          accept=".docx"
          onChange={handleUpload}
          className="hidden"
        />
        <Button
          onClick={() => fileRef.current?.click()}
          disabled={uploading}
          className="gap-1.5"
        >
          <Upload className="size-3.5" />
          {uploading ? '解析中...' : '上传 Word 模板'}
        </Button>
      </PageHeader>

      <div className="py-6">
        {isLoading ? (
          <p className="text-sm text-muted-foreground">加载中...</p>
        ) : templates.length === 0 ? (
          <div className="rounded-lg border border-dashed p-12 text-center text-sm text-muted-foreground">
            还没有模板，上传一个 Word 模板开始
          </div>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {templates.map((t) => (
              <Card key={t.id}>
                <CardHeader className="pb-3">
                  <CardTitle className="flex items-center gap-2 text-[15px]">
                    {t.name}
                    {t.is_system && <Badge variant="secondary">系统</Badge>}
                    {t.is_default && <Badge>默认</Badge>}
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <p className="text-[12px] text-muted-foreground">
                    {t.section_count} 个章节
                  </p>
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </div>
    </PageShell>
  )
}
