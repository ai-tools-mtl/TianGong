'use client'

import { BarChart3, FileText, Globe, Search, Settings } from 'lucide-react'
import Link from 'next/link'

import { PageHeader, PageShell } from '@/components/page-shell'
import { Card, CardContent } from '@/components/ui/card'

const CONSOLE_SECTIONS = [
  {
    href: '/admin/console/llm',
    icon: Settings,
    title: 'LLM 配置',
    description: '全局对话与嵌入模型凭据',
  },
  {
    href: '/admin/console/firecrawl',
    icon: Globe,
    title: 'Firecrawl 配置',
    description: '网页摄入 API 凭据',
  },
  {
    href: '/admin/console/stats',
    icon: BarChart3,
    title: '调用统计',
    description: 'LLM 与 Firecrawl 用量',
  },
  {
    href: '/admin/console/retrieval-test',
    icon: Search,
    title: '检索测试',
    description: '验证 RAG 召回质量，调参闭环',
  },
  {
    href: '/admin/console/audit',
    icon: FileText,
    title: '审计日志',
    description: '管理员操作记录',
  },
] as const

export default function ConsoleIndexPage() {
  return (
    <PageShell>
      <PageHeader title="控制台" description="系统配置与监控" />
      <div className="grid gap-4 py-6 sm:grid-cols-2">
        {CONSOLE_SECTIONS.map(({ href, icon: Icon, title, description }) => (
          <Link key={href} href={href}>
            <Card className="apple-lift transition-shadow hover:shadow-[var(--shadow-lift)]">
              <CardContent className="flex items-start gap-3 p-5">
                <div className="rounded-lg bg-muted p-2">
                  <Icon className="size-5" />
                </div>
                <div className="min-w-0">
                  <div className="text-sm font-medium">{title}</div>
                  <div className="mt-0.5 text-xs text-muted-foreground">
                    {description}
                  </div>
                </div>
              </CardContent>
            </Card>
          </Link>
        ))}
      </div>
    </PageShell>
  )
}
