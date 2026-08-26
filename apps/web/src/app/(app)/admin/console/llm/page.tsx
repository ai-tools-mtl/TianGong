'use client'

import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import { PageShell, PageHeader } from '@/components/page-shell'
import { Switch } from '@/components/ui/switch'
import { Button } from '@/components/ui/button'
import { LLMConfigEditPanel } from '@/components/llm-config/LLMConfigEditPanel'
import { TestResultBadge } from '@/components/llm-config/TestResultBadge'
import { api } from '@/lib/api'
import { queryKeys } from '@/lib/queries'
import {
  useGlobalLLMConfig,
  useLiteConfig,
  useSaveGlobalLLM,
  useSaveLiteConfig,
  useTestGlobalChat,
  useTestLiteChat,
} from '@/lib/queries'
import type { TestConnectionResult } from '@/types/api'

/**
 * /admin/console/llm 全局 LLM 配置。
 *
 * 三块：
 * 1. Chat 全局配置（embedding 已改走固定 bge-m3 微服务，不可配）。enabled 开关控制
 *    是否向用户提供全局 chat Key（后端 llm_global_enabled）。
 * 2. 轻量任务模型配置（会话标题/章节摘要，默认 GLM-4.7-Flash）。独立第三套凭据，
 *    未配置时后端回退到 Chat 全局/用户配置——所以这里是一块可选优化项，不配也不影响功能。
 * 3. 余额告警（优化计划批次 2b）：手动探测全局 Key 账户余额（仅 DeepSeek 支持），
 *    低于阈值时 console 全域顶部横幅告警。api_key 留空 = 不修改（后端只在传值时更新）。审计只记非敏感字段。
 */
export default function AdminLLMPage() {
  const [enabled, setEnabled] = useState(true)
  const [hydrated, setHydrated] = useState(false)
  const [chatRecheck, setChatRecheck] = useState<TestConnectionResult | null>(null)
  const [liteRecheck, setLiteRecheck] = useState<TestConnectionResult | null>(null)

  const cfgQuery = useGlobalLLMConfig()
  const saveMut = useSaveGlobalLLM()
  const testChat = useTestGlobalChat()

  const liteQuery = useLiteConfig()
  const saveLite = useSaveLiteConfig()
  const testLite = useTestLiteChat()

  // 余额告警（批次 2b）：阈值 + 手动探测
  const qc = useQueryClient()
  const balanceQuery = useQuery({
    queryKey: queryKeys.admin.llmBalance,
    queryFn: api.getLlmBalance,
  })
  const [thresholdInput, setThresholdInput] = useState('')
  const [probing, setProbing] = useState(false)
  const balance = balanceQuery.data

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

  const liteCfg = liteQuery.data

  async function handleRecheckLite() {
    try {
      const res = await testLite.mutateAsync({}) // 空 body → 用已存轻量配置值
      setLiteRecheck(res)
    } catch {
      toast.error('复检请求失败')
    }
  }

  async function handleProbeBalance() {
    setProbing(true)
    try {
      const res = await api.probeLlmBalance()
      await qc.invalidateQueries({ queryKey: queryKeys.admin.llmBalance })
      if (res.status === 'ok') {
        toast.success(`余额正常：${res.amount?.toFixed(2)} ${res.currency}`)
      } else if (res.status === 'low') {
        toast.error(`余额低：${res.amount?.toFixed(2)} ${res.currency}（阈值 ${res.threshold?.toFixed(2)}）`)
      } else if (res.status === 'error') {
        toast.error(res.error ?? '探测失败')
      } else {
        toast.info(
          res.status === 'unsupported' ? '当前 provider 不支持余额探测（仅 DeepSeek）'
            : '未配置全局 Chat Key',
        )
      }
    } catch {
      toast.error('探测请求失败')
    } finally {
      setProbing(false)
    }
  }

  async function handleSaveThreshold() {
    const v = Number(thresholdInput)
    if (!Number.isFinite(v) || v < 0) {
      toast.error('阈值需为非负数字')
      return
    }
    try {
      await api.setLlmBalanceThreshold(v)
      await qc.invalidateQueries({ queryKey: queryKeys.admin.llmBalance })
      setThresholdInput('')
      toast.success(`低额阈值已设为 ${v} 元`)
    } catch {
      toast.error('保存阈值失败')
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
            {/* 配置未就绪不挂载面板：面板 state 只在挂载时取 initial，
                query pending 时先挂载会把字段永久固化为空（data 到达不回填） */}
            {cfgQuery.isLoading ? (
              <p className="p-5 text-[12px] text-muted-foreground">加载配置…</p>
            ) : (
              <LLMConfigEditPanel
                showName={false}
                initial={
                  chatCfg
                    ? {
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
            )}
          </div>
        </div>

        {/* 轻量任务模型配置（会话标题/章节摘要；默认 GLM-4.7-Flash，未配回退上方 Chat 配置）*/}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <div className="space-y-0.5">
              <h3 className="text-[14px] font-semibold">轻量任务模型</h3>
              <p className="text-[12px] text-muted-foreground">
                用于会话标题、章节摘要等高频轻量任务，建议填免费通用的 GLM-4.7-Flash 以省 token
                {!liteCfg?.configured && '（当前未配置，正在回退到上方 Chat 配置）'}
              </p>
            </div>
            <Button size="sm" variant="outline" onClick={handleRecheckLite} disabled={testLite.isPending}>
              {testLite.isPending ? '复检中…' : '↻ 用已存配置测试'}
            </Button>
          </div>
          {liteRecheck && <TestResultBadge result={liteRecheck} />}
          <div
            className="overflow-hidden rounded-2xl border border-black/[0.07] bg-card dark:border-white/10"
            style={{ boxShadow: 'var(--shadow-card)' }}
          >
            {/* 同上：pending 期不挂载，避免 initial 空值固化 state */}
            {liteQuery.isLoading ? (
              <p className="p-5 text-[12px] text-muted-foreground">加载配置…</p>
            ) : (
              <LLMConfigEditPanel
                showName={false}
                initial={
                  liteCfg
                    ? {
                        base_url: liteCfg.base_url,
                        api_key_masked: liteCfg.api_key_masked,
                        model: liteCfg.model,
                        provider_template_id: 'zhipu',
                      }
                    : { provider_template_id: 'zhipu' }
                }
                saveLabel="保存轻量任务模型"
                onCancel={() => toast.info('轻量配置无需取消（常驻）')}
                onSave={async (d) => {
                  await saveLite.mutateAsync({
                    lite_config: {
                      base_url: d.base_url,
                      api_key: d.api_key || undefined, // 留空=不改
                      model: d.model,
                    },
                  })
                  toast.success('轻量任务模型配置已更新')
                }}
              />
            )}
          </div>
        </div>
        {/* 余额告警（优化计划批次 2b）：手动探测 + 低额阈值 */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <div className="space-y-0.5">
              <h3 className="text-[14px] font-semibold">余额告警</h3>
              <p className="text-[12px] text-muted-foreground">
                探测全局 Key 账户余额（仅 DeepSeek 支持）；低于阈值时 console 顶部横幅告警
              </p>
            </div>
            <Button size="sm" variant="outline" onClick={handleProbeBalance} disabled={probing}>
              {probing ? '探测中…' : '↻ 立即探测'}
            </Button>
          </div>
          <div
            className="flex flex-wrap items-center gap-x-6 gap-y-3 rounded-2xl border border-black/[0.07] bg-card px-5 py-4 dark:border-white/10"
            style={{ boxShadow: 'var(--shadow-card)' }}
          >
            <div className="text-[13px]">
              <span className="text-muted-foreground">最近探测：</span>
              {balance?.last ? (
                <span
                  className={
                    balance.last.status === 'low'
                      ? 'font-medium text-destructive'
                      : balance.last.status === 'ok'
                        ? 'font-medium text-success'
                        : 'font-medium text-amber-600 dark:text-amber-400'
                  }
                >
                  {balance.last.status === 'ok' && `正常 ${balance.last.amount?.toFixed(2)} ${balance.last.currency}`}
                  {balance.last.status === 'low' && `低额 ${balance.last.amount?.toFixed(2)} ${balance.last.currency}`}
                  {balance.last.status === 'error' && `失败（${balance.last.error}）`}
                  {balance.last.status === 'unsupported' && '当前 provider 不支持（仅 DeepSeek）'}
                  {balance.last.status === 'unconfigured' && '未配置全局 Chat Key'}
                </span>
              ) : (
                <span className="text-muted-foreground">从未探测</span>
              )}
              {balance?.last && (
                <span className="ml-2 text-[12px] text-muted-foreground">
                  {new Date(balance.last.probed_at).toLocaleString('zh-CN')}
                </span>
              )}
            </div>
            <div className="flex items-center gap-2 text-[13px]">
              <span className="text-muted-foreground">低额阈值：</span>
              <span className="font-medium tabular-nums">{balance?.threshold?.toFixed(2) ?? '—'} 元</span>
              <input
                value={thresholdInput}
                onChange={(e) => setThresholdInput(e.target.value)}
                placeholder="新阈值"
                inputMode="decimal"
                className="h-8 w-20 rounded border bg-background px-2 text-[13px] tabular-nums"
              />
              <Button size="sm" variant="outline" className="h-8" onClick={handleSaveThreshold} disabled={!thresholdInput.trim()}>
                保存
              </Button>
            </div>
          </div>
        </div>
      </div>
    </PageShell>
  )
}
