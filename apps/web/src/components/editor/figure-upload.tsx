'use client'

import { Check, ImageIcon, Loader2, Sparkles, X } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { api } from '@/lib/api'
import { getChatDefaultSource } from '@/lib/llm-source'
import { useAuthImage } from '@/lib/use-auth-image'

interface FigureUploadProps {
  sectionId: string
  projectId: string
  /** 插入编辑器：src + alt（有 AI 图注用图注，否则用文件名） */
  onInsertImage: (src: string, alt: string) => void
}

/** 上传后的预览态：附件 id + 文件名 + 图片 URL（AI 看图写注 / 插入正文） */
interface Uploaded {
  attachmentId: string
  filename: string
  src: string
}

/**
 * 附图上传（两步流）：上传 → 预览（AI 看图写注，复用 caption-figures 端点，
 * vision 模型多模态/文字降级在后端处理）→ 带图注插入正文。
 * 图注可手改；留空则用文件名作 alt。
 */
export function FigureUpload({ sectionId, projectId, onInsertImage }: FigureUploadProps) {
  const [uploading, setUploading] = useState(false)
  const [uploaded, setUploaded] = useState<Uploaded | null>(null)
  const [captionText, setCaptionText] = useState('')
  const [captioning, setCaptioning] = useState(false)

  // 鉴权图片加载：fetch + credentials 转 blob URL，绕过 <img> 跨端口 cookie 限制
  const authedImgUrl = useAuthImage(uploaded?.src ?? null)

  async function handleFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    setUploading(true)
    try {
      const att = await api.uploadAttachment(sectionId, file)
      setUploaded({
        attachmentId: att.id,
        filename: file.name,
        src: api.attachmentUrl(projectId, att.id),
      })
      setCaptionText('')
      toast.success('图片已上传，可 AI 生成图注后插入')
    } catch {
      toast.error('上传失败（仅支持 PNG/JPEG/GIF，≤10MB）')
    } finally {
      setUploading(false)
      e.target.value = '' // 允许重复选同一文件
    }
  }

  async function handleCaption() {
    if (!uploaded) return
    // source 为 null 走后端 fallback 链，不前端硬拦（同 ai-chat-panel）
    const source = getChatDefaultSource()
    setCaptioning(true)
    setCaptionText('')
    try {
      await api.captionFigures(
        sectionId,
        { attachment_ids: [uploaded.attachmentId], chat_source: source },
        (t) => setCaptionText((prev) => prev + t),
      )
    } catch (err: unknown) {
      toast.error((err as { message?: string })?.message ?? '图注生成失败')
    } finally {
      setCaptioning(false)
    }
  }

  function handleInsert() {
    if (!uploaded) return
    onInsertImage(uploaded.src, captionText.trim() || uploaded.filename)
    setUploaded(null)
    setCaptionText('')
    toast.success('已插入文档')
  }

  return (
    <div className="flex flex-col gap-2">
      <Button variant="outline" size="sm" className="h-8 gap-1.5" disabled={uploading} asChild>
        <label className="cursor-pointer">
          {uploading ? <Loader2 className="size-3.5 animate-spin" /> : <ImageIcon className="size-3.5" />}
          {uploading ? '上传中...' : '上传图片'}
          <input type="file" accept="image/png,image/jpeg,image/gif" onChange={handleFile} className="hidden" />
        </label>
      </Button>

      {uploaded && (
        <div className="space-y-2 rounded-md border p-2">
          {/* 预览 */}
          <div className="flex items-start gap-2">
            {authedImgUrl ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={authedImgUrl}
                alt={uploaded.filename}
                className="h-20 w-28 shrink-0 rounded border object-contain"
              />
            ) : (
              <div className="grid h-20 w-28 shrink-0 place-items-center rounded border bg-muted text-muted-foreground">
                <Loader2 className="size-4 animate-spin" />
              </div>
            )}
            <div className="min-w-0 flex-1 space-y-1.5">
              <div className="truncate text-[11px] text-muted-foreground" title={uploaded.filename}>
                {uploaded.filename}
              </div>
              <div className="flex flex-wrap gap-1.5">
                <Button
                  variant="outline"
                  size="xs"
                  className="h-7 gap-1"
                  onClick={handleCaption}
                  disabled={captioning}
                >
                  {captioning ? <Loader2 className="size-3 animate-spin" /> : <Sparkles className="size-3" />}
                  {captioning ? '看图写注中...' : 'AI 看图写注'}
                </Button>
                <Button size="xs" className="h-7 gap-1" onClick={handleInsert}>
                  <Check className="size-3" />
                  插入正文
                </Button>
                <Button
                  variant="ghost"
                  size="icon-xs"
                  aria-label="丢弃"
                  title="丢弃（不插入）"
                  onClick={() => {
                    setUploaded(null)
                    setCaptionText('')
                  }}
                >
                  <X className="size-3.5" />
                </Button>
              </div>
            </div>
          </div>
          {/* 图注（可手改） */}
          <textarea
            value={captionText}
            onChange={(e) => setCaptionText(e.target.value)}
            placeholder={captioning ? 'AI 正在看图写注...' : '图注（可点 AI 生成，可手动编辑；留空则用文件名）'}
            rows={2}
            className="w-full resize-none rounded border bg-background px-2 py-1.5 text-[12px] leading-relaxed outline-none focus-visible:ring-1 focus-visible:ring-ring"
          />
        </div>
      )}
    </div>
  )
}
