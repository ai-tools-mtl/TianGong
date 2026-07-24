'use client'

import { useEffect, useState } from 'react'
import { toast } from 'sonner'

import { PageShell, PageHeader } from '@/components/page-shell'
import { Switch } from '@/components/ui/switch'
import { Button } from '@/components/ui/button'
import { LLMConfigEditPanel } from '@/components/llm-config/LLMConfigEditPanel'
import { TestResultBadge } from '@/components/llm-config/TestResultBadge'
import { useGlobalLLMConfig, useSaveGlobalLLM, useTestGlobalLLM } from '@/lib/queries'
import type { TestConnectionResult } from '@/types/api'

/**
 * /admin/console/llm 全局 LLM 配置（feat/llm-config-redesign Task 18）。
 *
 * 复用 LLMConfigEditPanel（adminMode 常驻显示），在其之上叠加：
 *   - enabled 开关（是否提供全局 Key，关闭则强制用户自配）
 *   - “用已存配置测试”复检按钮（空 body → 后端用已存值跑 chat+embedding 双测）
 *
 * enabled 是独立 state（one-shot hydrate 一次，避免覆盖编辑），保存时与配置一起下发。
 * api_key 留空 = 不修改（后端只在传值时更新）。审计只记非敏感字段。
 */
export default function AdminLLMPage() {
  const [enabled, setEnabled] = useState(true)
  const [hydrated, setHydrated] = useState(false)
  const [recheckResult, setRecheckResult] = useState<TestConnectionResult | null>(null)

  const cfgQuery = useGlobalLLMConfig()
  const saveMut = useSaveGlobalLLM()
  const testGlobal = useTestGlobalLLM()

  // 一次性 hydrate（避免覆盖编辑）。用独立 hydrated flag，仅在首次拿到数据时写入。
  useEffect(() => {
    if (!hydrated && cfgQuery.data) {
      setEnabled(cfgQuery.data.llm_global_enabled)
      setHydrated(true)
    }
  }, [hydrated, cfgQuery.data])

  const gc = cfgQuery.data?.global_config

  async function handleRecheck() {
    try {
      const res = await testGlobal.mutateAsync({}) // 空 body → 用已存值
      setRecheckResult(res)
    } catch {
      // mutateAsync 抛错时 react-query 不走 onError（这里没配），toast 兜底
      toast.error('复检请求失败')
    }
  }

  return (
    <PageShell>
      <PageHeader title="全局 LLM 配置" description="管理员配置供全平台使用的 LLM（用户可申请授权使用）">
        <Button size="sm" variant="outline" onClick={handleRecheck} disabled={testGlobal.isPending}>
          {testGlobal.isPending ? '复检中…' : '↻ 用已存配置测试'}
        </Button>
      </PageHeader>

      <div className="py-6 space-y-5">
        {/* enabled 开关 */}
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

        {/* 复检结果 */}
        {recheckResult && <TestResultBadge result={recheckResult} />}

        {/* 编辑面板（admin 模式：常驻显示） */}
        <div
          className="overflow-hidden rounded-2xl border border-black/[0.07] bg-card dark:border-white/10"
          style={{ boxShadow: 'var(--shadow-card)' }}
        >
          <LLMConfigEditPanel
            initial={
              gc
                ? {
                    name: '全局 Key',
                    base_url: gc.base_url,
                    api_key_masked: gc.api_key_masked,
                    model: gc.model,
                    embedding_model: gc.embedding_model,
                  }
                : null
            }
            adminMode
            initialAllowedModels={gc?.allowed_models ?? []}
            saveLabel="保存全局配置"
            onCancel={() => toast.info('全局配置无需取消（常驻）')}
            onSave={async (d) => {
              await saveMut.mutateAsync({
                enabled,
                base_url: d.base_url,
                api_key: d.api_key || undefined, // 留空=不改
                model: d.model,
                // panel 回传 string | null；saveMut 期望 string，空值传 undefined（不更新）
                embedding_model: d.embedding_model || undefined,
                allowed_models: d.allowed_models
                  ? (d.allowed_models as string)
                      .split(',')
                      .map((s) => s.trim())
                      .filter(Boolean)
                  : undefined,
              })
              toast.success('全局 LLM 配置已更新')
            }}
          />
        </div>
      </div>
    </PageShell>
  )
}
