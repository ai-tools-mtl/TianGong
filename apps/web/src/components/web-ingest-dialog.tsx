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
