'use client'

import { useState } from 'react'
import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import type { Skill, SkillCreate, SkillStatus, SkillUpdate } from '@/types/api'

/**
 * Skill 编辑器（表单式，admin/user 共用）。
 *
 * v1 范围：name + description（单行，触发条件）+ skill_md 正文大文本框 + 状态切换。
 * scripts/references/assets 文件上传留 v2（spec §12）。
 *
 * frontmatter round-trip：detail 接口返回完整 SKILL.md（含 frontmatter），
 * 编辑器加载时剥离 frontmatter 只显示正文；保存时只传 body（后端重新组装 frontmatter）。
 */
interface SkillEditorProps {
  /** 已有 skill（编辑模式）；null = 创建模式 */
  skill: Skill | null
  /** 初始 SKILL.md 正文（编辑模式从 detail 接口加载，含 frontmatter，本组件会剥离） */
  initialSkillMd?: string
  mode: 'global' | 'personal'
  onSave: (data: SkillCreate | SkillUpdate) => Promise<void>
  onCancel: () => void
}

/** 从完整 SKILL.md（含 frontmatter）剥离出正文。 */
function stripFrontmatter(md: string): string {
  if (!md.startsWith('---\n')) return md
  const parts = md.split('---\n', 3)
  // 格式：---\n<frontmatter>\n---\n<body>
  if (parts.length >= 3) return parts[2].replace(/^\n+/, '')
  return md
}

export function SkillEditor({ skill, initialSkillMd, mode, onSave, onCancel }: SkillEditorProps) {
  const isEdit = skill !== null
  const [name, setName] = useState(skill?.name ?? '')
  const [description, setDescription] = useState(skill?.description ?? '')
  const [skillMd, setSkillMd] = useState(initialSkillMd ? stripFrontmatter(initialSkillMd) : '')
  const [status, setStatus] = useState<SkillStatus>(skill?.status ?? 'draft')
  const [saving, setSaving] = useState(false)

  async function handleSave() {
    if (!name.trim() || !description.trim()) {
      toast.error('name 和 description 必填')
      return
    }
    // description 单行校验（spec 触发条件约束）
    if (description.includes('\n')) {
      toast.error('description 必须单行（spec 触发条件约束）')
      return
    }
    setSaving(true)
    try {
      const payload: SkillCreate | SkillUpdate = isEdit
        ? { description, skill_md: skillMd, status }
        : { name, description, skill_md: skillMd }
      await onSave(payload)
      toast.success(isEdit ? '技能已更新' : '技能已创建')
      onCancel()
    } catch (e) {
      toast.error('保存失败：' + (e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <label className="text-sm font-medium">name（spec 标识，[a-z0-9-]，≤64）</label>
        <Input
          value={name}
          onChange={(e) => setName(e.target.value)}
          disabled={isEdit}
          placeholder="my-skill"
        />
        {isEdit && <p className="text-xs text-muted-foreground">name 创建后不可改（spec: name=目录名）</p>}
      </div>

      <div className="space-y-2">
        <label className="text-sm font-medium">description（触发条件，单行 ≤1024）</label>
        <Input
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="什么任务该激活这个技能"
        />
      </div>

      <div className="space-y-2">
        <label className="text-sm font-medium">SKILL.md 正文（Markdown，不含 frontmatter）</label>
        <Textarea
          value={skillMd}
          onChange={(e) => setSkillMd(e.target.value)}
          rows={12}
          placeholder={'## 步骤\n1. 分析技术领域\n2. ...'}
        />
      </div>

      {isEdit && (
        <div className="flex items-center gap-2">
          <label className="text-sm font-medium">状态</label>
          <Badge variant={status === 'active' ? 'default' : 'secondary'}>{status}</Badge>
          <Button
            size="sm"
            variant="outline"
            onClick={() => setStatus(status === 'draft' ? 'active' : 'draft')}
          >
            切换为 {status === 'draft' ? 'active' : 'draft'}
          </Button>
          <span className="text-xs text-muted-foreground">draft 不进 runtime，active 进</span>
        </div>
      )}

      <div className="flex justify-end gap-2">
        <Button variant="outline" onClick={onCancel} disabled={saving}>取消</Button>
        <Button onClick={handleSave} disabled={saving}>
          {saving ? '保存中...' : isEdit ? '更新' : '创建'}
        </Button>
      </div>
    </div>
  )
}
