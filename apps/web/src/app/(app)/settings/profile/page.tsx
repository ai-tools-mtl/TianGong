'use client'

import { useEffect, useState } from 'react'
import { toast } from 'sonner'

import { PageHeader, PageShell } from '@/components/page-shell'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { useUpdateWritingProfile, useWritingProfile } from '@/lib/queries'
import type { WritingProfileUpdate } from '@/types/api'

const PROFICIENCY_OPTIONS = [
  { value: 'novice', label: '初学者（发明人/技术新人）', hint: 'Agent 会通俗化专利术语' },
  { value: 'intermediate', label: '一般技术人员', hint: '平衡专业与通俗' },
  { value: 'expert', label: '专家（专利代理人/律师）', hint: 'Agent 会使用高密度专利术语' },
] as const

const PROFESSION_SUGGESTIONS = [
  '专利代理人', '专利律师', '发明人', '研发工程师', '研究员', '审查员',
]

export default function WritingProfilePage() {
  const { data: profile, isLoading } = useWritingProfile()
  const updateMut = useUpdateWritingProfile()

  const [profession, setProfession] = useState('')
  const [techDomain, setTechDomain] = useState('')
  const [proficiency, setProficiency] = useState('')
  const [writingStyle, setWritingStyle] = useState('')
  const [terminology, setTerminology] = useState('')

  // hydrate：query 数据返回后一次性灌入表单
  useEffect(() => {
    if (profile) {
      setProfession(profile.profession ?? '')
      setTechDomain(profile.tech_domain ?? '')
      setProficiency(profile.proficiency ?? '')
      setWritingStyle(profile.writing_style ?? '')
      setTerminology(profile.terminology ?? '')
    }
  }, [profile])

  const onSave = () => {
    const data: WritingProfileUpdate = {}
    // 只发送有变化的字段（后端 upsert 仅更新非 None 字段）
    if (profession !== (profile?.profession ?? '')) data.profession = profession || undefined
    if (techDomain !== (profile?.tech_domain ?? '')) data.tech_domain = techDomain || undefined
    if (proficiency !== (profile?.proficiency ?? '')) {
      data.proficiency = (proficiency || undefined) as WritingProfileUpdate['proficiency']
    }
    if (writingStyle !== (profile?.writing_style ?? '')) data.writing_style = writingStyle || undefined
    if (terminology !== (profile?.terminology ?? '')) data.terminology = terminology || undefined

    if (Object.keys(data).length === 0) {
      toast.info('没有改动')
      return
    }
    updateMut.mutate(data, {
      onSuccess: () => toast.success('画像已保存'),
      onError: () => toast.error('保存失败'),
    })
  }

  if (isLoading) {
    return (
      <PageShell>
        <PageHeader title="写作画像" description="加载中…" />
      </PageShell>
    )
  }

  return (
    <PageShell>
      <PageHeader
        title="写作画像"
        description="填写你的职业身份和技术偏好。Agent 每次生成时都会遵循这些设定。"
      />

      <div className="my-6 space-y-6">
        {/* 职业身份 */}
        <div className="space-y-2">
          <Label>职业身份</Label>
          <Input
            value={profession}
            onChange={(e) => setProfession(e.target.value)}
            placeholder="如：专利代理人"
            list="profession-suggestions"
            maxLength={100}
          />
          <datalist id="profession-suggestions">
            {PROFESSION_SUGGESTIONS.map((s) => (
              <option key={s} value={s} />
            ))}
          </datalist>
          <p className="text-[12px] text-muted-foreground">
            驱动 Agent 的表达密度——代理人看术语，发明人看大白话
          </p>
        </div>

        {/* 技术领域 */}
        <div className="space-y-2">
          <Label>技术领域</Label>
          <Input
            value={techDomain}
            onChange={(e) => setTechDomain(e.target.value)}
            placeholder="如：机械工程 / 半导体 / 新能源电池"
            maxLength={100}
          />
          <p className="text-[12px] text-muted-foreground">
            帮 Agent 理解你的领域语境，生成更贴合的内容
          </p>
        </div>

        {/* 专业水平 */}
        <div className="space-y-2">
          <Label>专业水平</Label>
          <div className="space-y-2">
            {PROFICIENCY_OPTIONS.map((opt) => (
              <label
                key={opt.value}
                className={`flex cursor-pointer items-start gap-3 rounded-xl border p-3 transition-colors ${
                  proficiency === opt.value
                    ? 'border-foreground/30 bg-black/[0.02] dark:bg-white/[0.04]'
                    : 'border-black/[0.07] hover:bg-black/[0.01] dark:border-white/10'
                }`}
              >
                <input
                  type="radio"
                  name="proficiency"
                  value={opt.value}
                  checked={proficiency === opt.value}
                  onChange={(e) => setProficiency(e.target.value)}
                  className="mt-0.5"
                />
                <div>
                  <p className="text-[14px] font-medium">{opt.label}</p>
                  <p className="text-[12px] text-muted-foreground">{opt.hint}</p>
                </div>
              </label>
            ))}
          </div>
        </div>

        {/* 写作风格偏好 */}
        <div className="space-y-2">
          <Label>写作风格偏好</Label>
          <Textarea
            value={writingStyle}
            onChange={(e) => setWritingStyle(e.target.value)}
            placeholder="如：简洁直接，少用形容词 / 详尽覆盖每个细节 / 口语化表达"
            rows={3}
          />
        </div>

        {/* 术语偏好 */}
        <div className="space-y-2">
          <Label>术语偏好</Label>
          <Textarea
            value={terminology}
            onChange={(e) => setTerminology(e.target.value)}
            placeholder="如：用「5G」不用「蜂窝」 / 权利要求统一用「所述」 / 避免口语"
            rows={3}
          />
        </div>

        <div className="flex justify-end">
          <Button onClick={onSave} disabled={updateMut.isPending}>
            {updateMut.isPending ? '保存中…' : '保存画像'}
          </Button>
        </div>
      </div>
    </PageShell>
  )
}
