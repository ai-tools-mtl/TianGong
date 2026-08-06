'use client'

import { useState } from 'react'
import { Eye, EyeOff } from 'lucide-react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { api } from '@/lib/api'
import type { IMATestResult } from '@/types/api'

export interface IMAConfigPanelProps {
  /** 编辑模式初始值（掩码）；新增模式传 null。 */
  initial?: {
    client_id_masked?: string
    api_key_masked?: string
  } | null
  /** 保存回调。apiKey/clientId 留空串 = 不改。 */
  onSave: (data: { client_id: string; api_key: string }) => Promise<void>
  onCancel: () => void
}

/**
 * 腾讯 ima 检索源配置面板（单配置，字段仅 Client ID + API Key）。
 * 照抄 LLMConfigEditPanel 的显隐/测试/留空不改交互，去掉 model/base_url/模板。
 */
export function IMAConfigPanel({ initial, onSave, onCancel }: IMAConfigPanelProps) {
  const [clientId, setClientId] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [showId, setShowId] = useState(false)
  const [showKey, setShowKey] = useState(false)
  const [testResult, setTestResult] = useState<IMATestResult | null>(null)
  const [testing, setTesting] = useState(false)
  const [saving, setSaving] = useState(false)

  const isEdit = !!initial?.api_key_masked  // 编辑模式（已有配置）

  async function handleTest() {
    // 编辑模式未改 key 时无法测（已存 Key 不回显明文）
    if (!clientId || !apiKey) {
      if (isEdit && !clientId && !apiKey) {
        toast.error('测试需重新填写 Client ID 和 API Key（已存凭据不回显明文）')
        return
      }
      toast.error('请先填写 Client ID 和 API Key')
      return
    }
    setTesting(true)
    try {
      const res = await api.testMyIMA({ client_id: clientId, api_key: apiKey })
      setTestResult(res)
      if (res.ok) {
        toast.success(`连接成功${res.hit_count > 0 ? `，命中 ${res.hit_count} 条` : ''}`)
      } else {
        toast.error(`连接失败：${res.error ?? '未知错误'}`)
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : '测试失败')
    } finally {
      setTesting(false)
    }
  }

  async function handleSave() {
    // 新增模式：两个凭据都必填
    if (!isEdit && (!clientId || !apiKey)) {
      toast.error('首次配置必须填写 Client ID 和 API Key')
      return
    }
    setSaving(true)
    try {
      await onSave({ client_id: clientId, api_key: apiKey })
    } catch (e) {
      toast.error(`保存失败：${e instanceof Error ? e.message : String(e)}`)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-4 bg-muted/20 p-5">
      {/* Client ID */}
      <div className="space-y-1.5">
        <Label className="text-[12px]">
          Client ID
          {initial?.client_id_masked && (
            <span className="ml-2 text-[11px] text-muted-foreground">
              当前：{initial.client_id_masked}（留空不修改）
            </span>
          )}
        </Label>
        <div className="relative">
          <Input
            type={showId ? 'text' : 'password'}
            value={clientId}
            onChange={(e) => setClientId(e.target.value)}
            placeholder={initial?.client_id_masked ? '输入新 Client ID（留空不改）' : '在 ima.qq.com/agent-interface 获取'}
            className="pr-10 font-mono"
          />
          <button
            type="button"
            onClick={() => setShowId((s) => !s)}
            className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
            aria-label={showId ? '隐藏' : '显示'}
          >
            {showId ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
          </button>
        </div>
      </div>

      {/* API Key */}
      <div className="space-y-1.5">
        <Label className="text-[12px]">
          API Key
          {initial?.api_key_masked && (
            <span className="ml-2 text-[11px] text-muted-foreground">
              当前：{initial.api_key_masked}（留空不修改）
            </span>
          )}
        </Label>
        <div className="relative">
          <Input
            type={showKey ? 'text' : 'password'}
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder={initial?.api_key_masked ? '输入新 Key（留空不改）' : '输入 API Key'}
            className="pr-10 font-mono"
          />
          <button
            type="button"
            onClick={() => setShowKey((s) => !s)}
            className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
            aria-label={showKey ? '隐藏' : '显示'}
          >
            {showKey ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
          </button>
        </div>
      </div>

      {/* 说明 */}
      <p className="text-[11px] leading-relaxed text-muted-foreground">
        在 <a href="https://ima.qq.com/agent-interface" target="_blank" rel="noopener noreferrer" className="underline">ima.qq.com/agent-interface</a> 生成 Client ID 和 API Key。
        开启后，每次章节对话会额外查询你的 ima 知识库（实时检索，不导入文件）。
      </p>

      {/* 测试结果 */}
      {testResult && (
        <div
          className={`rounded-md p-2.5 text-[12px] ${
            testResult.ok
              ? 'bg-success/10 text-success'
              : 'bg-destructive/10 text-destructive'
          }`}
        >
          {testResult.ok
            ? `✓ 连接成功${testResult.hit_count > 0 ? `，命中 ${testResult.hit_count} 个知识库` : '（未命中内容，但鉴权通过）'}`
            : `✗ 连接失败：${testResult.error ?? '请检查凭据或网络'}`}
        </div>
      )}

      {/* 操作 */}
      <div className="flex items-center justify-between border-t border-black/[0.07] pt-4 dark:border-white/10">
        <Button
          type="button" variant="outline" size="sm"
          disabled={testing}
          onClick={handleTest}
        >
          {testing ? '测试中…' : '↻ 测试连接'}
        </Button>
        <div className="flex gap-2">
          <Button type="button" variant="ghost" size="sm" onClick={onCancel}>取消</Button>
          <Button type="button" size="sm" disabled={saving} onClick={handleSave}>
            {saving ? '保存中…' : '保存'}
          </Button>
        </div>
      </div>
    </div>
  )
}
