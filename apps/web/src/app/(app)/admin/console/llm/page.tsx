'use client'

import { useEffect, useState } from 'react'
import { toast } from 'sonner'

import { PageShell, PageHeader } from '@/components/page-shell'
import { Switch } from '@/components/ui/switch'
import { Button } from '@/components/ui/button'
import { LLMConfigEditPanel } from '@/components/llm-config/LLMConfigEditPanel'
import { TestResultBadge } from '@/components/llm-config/TestResultBadge'
import {
  useGlobalLLMConfig,
  useSaveGlobalLLM,
  useTestGlobalChat,
} from '@/lib/queries'
import type { TestConnectionResult } from '@/types/api'

/**
 * /admin/console/llm 全局 LLM 配置。
 *
 * 只管 chat 全局配置（embedding 已改走固定 bge-m3 微服务，不可配）。
 * enabled 开关控制是否向用户提供全局 chat Key（后端 llm_global_enabled）。
 * api_key 留空 = 不修改（后端只在传值时更新）。审计只记非敏感字段。
 */
export default function AdminLLMPage() {
  const [enabled, setEnabled] = useState(true)
  const [hydrated, setHydrated] = useState(false)
  const [chatRecheck, setChatRecheck] = useState<TestConnectionResult | null>(null)

  const cfgQuery = useGlobalLLMConfig()
  const saveMut = useSaveGlobalLLM()
  const testChat = useTestGlobalChat()

  // 一次性 hydrate（避免覆盖编辑）。
  useEffect(() => {
    if (!hydrated && cfgQuery.data) {
      setEnabled(cfgQuery.data.llm_global_enabled)
      setHydrated(true)
    }
  }, [hydrated, cfgQuery.data])

  const chatCfg = cfgQuery.data?.chat_config

  async function handleRecheckChat() {
    try {
      const res = await testChat.mutateAsync({}) // 空 body → 用已存 chat 值
      setChatRecheck(res)
    } catch {
      toast.error('复检请求失败')
    }
  }

  return (
    <PageShell>
      <PageHeader title="全局 LLM 配置" description="管理员配置供全平台使用的全局 chat Key；embedding 统一走 bge-m3 微服务" />

      <div className="py-6 space-y-5">
        {/* enabled 开关（控制全局 chat Key） */}
        <div
          className="flex items-center justify-between rounded-2xl border border-black/[0.07] bg-card px-5 py-3.5 dark:border-white/10"
          style={{ boxShadow: 'var(--shadow-card)' }}
        >
          <div>
            <p className="text-[13px] font-medium">提供全局 Key</p>
            <p className="text-[12px] text-muted-foreground">
              {enabled
                ? '开启：用户被授权后可使用此全局 Key'
                : '关闭：强制用户使用自己的自定义配置'}
            </p>
          </div>
          <Switch checked={enabled} onCheckedChange={setEnabled} />
        </div>

        {/* Chat 全局配置 */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <h3 className="text-[14px] font-semibold">Chat 配置</h3>
            <Button size="sm" variant="outline" onClick={handleRecheckChat} disabled={testChat.isPending}>
              {testChat.isPending ? '复检中…' : '↻ 用已存配置测试'}
            </Button>
          </div>
          {chatRecheck && <TestResultBadge result={chatRecheck} />}
          <div
            className="overflow-hidden rounded-2xl border border-black/[0.07] bg-card dark:border-white/10"
            style={{ boxShadow: 'var(--shadow-card)' }}
          >
            <LLMConfigEditPanel
              initial={
                chatCfg
                  ? {
                      name: '全局 Chat Key',
                      base_url: chatCfg.base_url,
                      api_key_masked: chatCfg.api_key_masked,
                      model: chatCfg.model,
                    }
                  : null
              }
              saveLabel="保存全局 Chat 配置"
              onCancel={() => toast.info('全局配置无需取消（常驻）')}
              onSave={async (d) => {
                await saveMut.mutateAsync({
                  enabled,
                  chat_config: {
                    base_url: d.base_url,
                    api_key: d.api_key || undefined, // 留空=不改
                    model: d.model,
                  },
                })
                toast.success('全局 Chat 配置已更新')
              }}
            />
          </div>
        </div>
      </div>
    </PageShell>
  )
}
