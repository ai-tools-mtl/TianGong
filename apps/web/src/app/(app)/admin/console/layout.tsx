'use client'

import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'

import { api } from '@/lib/api'
import { queryKeys } from '@/lib/queries'
import type { LLMBalanceStatus } from '@/types/api'

/**
 * /admin/console 共用布局：余额告警横幅 + 页面内容。
 *
 * 横幅只在「low（低于阈值）」和「error（探测失败）」时渲染——ok/unsupported/
 * unconfigured 不打扰。数据是 admin 手动探测的结果（llm_balance_status），
 * 挂载时拉一次；探测入口在「全局 LLM 配置」页。关闭按「状态+时间」key 记忆：
 * 新一次探测产生新告警会重新显示。
 */
export default function AdminConsoleLayout({ children }: { children: React.ReactNode }) {
  const { data } = useQuery({
    queryKey: queryKeys.admin.llmBalance,
    queryFn: api.getLlmBalance,
    staleTime: 60_000,
  })

  return (
    <>
      <LLMBalanceBanner status={data?.last ?? null} />
      {children}
    </>
  )
}

function LLMBalanceBanner({ status }: { status: LLMBalanceStatus | null }) {
  const [dismissedKey, setDismissedKey] = useState<string | null>(null)
  if (!status || (status.status !== 'low' && status.status !== 'error')) return null

  const key = `${status.status}:${status.probed_at}`
  if (dismissedKey === key) return null

  if (status.status === 'low') {
    return (
      <div className="mb-2 flex items-center justify-between rounded-lg border border-destructive/40 bg-destructive/10 px-4 py-2 text-[13px] text-destructive">
        <span>
          ⚠️ 全局 LLM 账户余额低：{status.amount?.toFixed(2)} {status.currency}
          （阈值 {status.threshold?.toFixed(2)}）——欠费将导致未自配 Key 的用户集体不可用，请尽快充值
        </span>
        <button type="button" className="ml-4 shrink-0 text-destructive/70 hover:text-destructive" onClick={() => setDismissedKey(key)}>
          关闭
        </button>
      </div>
    )
  }
  return (
    <div className="mb-2 flex items-center justify-between rounded-lg border border-amber-500/40 bg-amber-500/10 px-4 py-2 text-[13px] text-amber-600 dark:text-amber-400">
      <span>余额探测失败：{status.error}——无法确认全局 Key 余额状态，建议到「全局 LLM 配置」页重新探测</span>
      <button type="button" className="ml-4 shrink-0 text-amber-600/70 hover:text-amber-600 dark:text-amber-400/70" onClick={() => setDismissedKey(key)}>
        关闭
      </button>
    </div>
  )
}
