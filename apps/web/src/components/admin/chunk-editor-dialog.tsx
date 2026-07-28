'use client'

import { useEffect, useState } from 'react'
import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { useUpdateChunk } from '@/lib/queries'

/**
 * G4 分块可视化干预（Task 4.4）：单 chunk 编辑对话框。
 *
 * 字段语义（与后端 PATCH /admin/knowledge/chunks/{id} 对齐）：
 * - edited_text：留空 = 用原 content（后端 None）；改了会触发重新 embed。
 * - keywords[]：进 tsv，参与关键词路召回加权。
 * - questions[]：进 tsv，参与关键词路召回。
 * - weight：召回分数乘子，默认 1.0。
 * - locked：锁定的 chunk 在 re-ingest 时不被覆盖。
 *
 * mutation 不弹 toast（queries.ts 约定），toast 在本组件层处理。
 * 抄 review-workbench.tsx / knowledge page 的 Dialog 模式。
 */
export type EditableChunk = {
  id: string
  content: string
  edited_text: string | null
  keywords: string[]
  questions: string[]
  weight: number
  locked: boolean
}

export function ChunkEditorDialog({
  chunk,
  open,
  onOpenChange,
}: {
  chunk: EditableChunk | null
  open: boolean
  onOpenChange: (v: boolean) => void
}) {
  const [editedText, setEditedText] = useState('')
  const [keywords, setKeywords] = useState<string[]>([])
  const [keywordInput, setKeywordInput] = useState('')
  const [questions, setQuestions] = useState<string[]>([])
  const [questionInput, setQuestionInput] = useState('')
  const [weight, setWeight] = useState(1.0)
  const [locked, setLocked] = useState(false)
  const update = useUpdateChunk()

  // chunk 切换时把表单同步成新值。每次打开（即使同一 chunk 编辑保存后再改）都 reset。
  useEffect(() => {
    if (chunk) {
      setEditedText(chunk.edited_text ?? '')
      setKeywords(chunk.keywords ?? [])
      setQuestions(chunk.questions ?? [])
      setWeight(chunk.weight ?? 1.0)
      setLocked(chunk.locked ?? false)
    }
  }, [chunk])

  if (!chunk) return null

  function handleSave() {
    if (!chunk) return
    update.mutate(
      {
        chunkId: chunk.id,
        payload: {
          // 空串不传（保留 None = 用原 content）
          edited_text: editedText.trim() || undefined,
          keywords,
          questions,
          weight,
          locked,
        },
      },
      {
        onSuccess: () => {
          toast.success('已保存（若改了文本会重新 embed）')
          onOpenChange(false)
        },
        onError: (err: { message?: string }) =>
          toast.error(err?.message ?? '保存失败'),
      },
    )
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] max-w-2xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            编辑分块
            {chunk.locked && <Badge variant="destructive">已锁定</Badge>}
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-4">
          <div>
            <Label>原始内容（只读）</Label>
            <pre className="mt-1 max-h-32 overflow-y-auto whitespace-pre-wrap rounded bg-muted p-2 text-xs">
              {chunk.content}
            </pre>
          </div>

          <div>
            <Label>编辑后内容（留空用原始内容，变更后触发重新 embed）</Label>
            <Textarea
              value={editedText}
              onChange={(e) => setEditedText(e.target.value)}
              rows={4}
              className="mt-1"
              placeholder="留空将沿用上方原始内容"
            />
          </div>

          <div>
            <Label>关键词（参与关键词路召回加权）</Label>
            <div className="mb-2 mt-1 flex flex-wrap gap-1.5">
              {keywords.map((k) => (
                <Badge
                  key={k}
                  variant="secondary"
                  className="cursor-pointer"
                  onClick={() => setKeywords(keywords.filter((x) => x !== k))}
                >
                  {k} ×
                </Badge>
              ))}
            </div>
            <Input
              value={keywordInput}
              onChange={(e) => setKeywordInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && keywordInput.trim()) {
                  e.preventDefault()
                  setKeywords([...keywords, keywordInput.trim()])
                  setKeywordInput('')
                }
              }}
              placeholder="输入后回车添加"
            />
          </div>

          <div>
            <Label>预设问题（参与关键词路召回）</Label>
            <div className="mb-2 mt-1 space-y-1">
              {questions.map((q, i) => (
                <div key={i} className="flex items-center gap-2">
                  <span className="flex-1 text-sm">{q}</span>
                  <Button
                    size="xs"
                    variant="ghost"
                    onClick={() =>
                      setQuestions(questions.filter((_, idx) => idx !== i))
                    }
                  >
                    ×
                  </Button>
                </div>
              ))}
            </div>
            <Input
              value={questionInput}
              onChange={(e) => setQuestionInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && questionInput.trim()) {
                  e.preventDefault()
                  setQuestions([...questions, questionInput.trim()])
                  setQuestionInput('')
                }
              }}
              placeholder="输入后回车添加"
            />
          </div>

          <div className="flex items-end gap-4">
            <div>
              <Label>权重（召回分数乘子，默认 1.0）</Label>
              <Input
                type="number"
                step="0.1"
                value={weight}
                onChange={(e) => setWeight(Number(e.target.value))}
                className="mt-1 w-24"
              />
            </div>
            <div className="flex items-center gap-2">
              <Switch checked={locked} onCheckedChange={setLocked} />
              <Label>锁定（防重新 ingest 覆盖）</Label>
            </div>
          </div>
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button onClick={handleSave} disabled={update.isPending}>
            {update.isPending ? '保存中...' : '保存'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
