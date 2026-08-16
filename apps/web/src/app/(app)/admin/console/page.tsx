'use client'

import { BarChart3, Database, Eye, FileText, ImageIcon, LifeBuoy, Plug, ScanText, Search, Settings, ShieldQuestion } from 'lucide-react'
import Link from 'next/link'

import { PageHeader, PageShell } from '@/components/page-shell'
import { Card, CardContent } from '@/components/ui/card'

const CONSOLE_SECTIONS = [
  {
    href: '/admin/console/llm',
    icon: Settings,
    title: 'LLM 配置',
    description: '全局对话模型凭据（嵌入统一走 bge-m3 微服务）',
  },
  {
    href: '/admin/console/mineru',
    icon: ScanText,
    title: 'MinerU 配置',
    description: 'PDF 转 Markdown 解析（保留表格/OCR）',
  },
  {
    href: '/admin/console/ima',
    icon: Database,
    title: 'ima 检索源',
    description: '腾讯 ima 知识库全局检索源凭据',
  },
  {
    href: '/admin/console/figure-presets',
    icon: ImageIcon,
    title: '附图风格预设',
    description: '专利附图配色与渲染规格（黑白/彩色/灰度）',
  },
  {
    href: '/admin/console/hitl',
    icon: ShieldQuestion,
    title: '工具确认（HITL）',
    description: 'agent 工具执行前的用户确认拦截清单',
  },
  {
    href: '/admin/console/support-view',
    icon: LifeBuoy,
    title: '支持查看',
    description: '凭用户授权码限时只读查看项目（全程审计）',
  },
  {
    href: '/admin/console/vision-markers',
    icon: Eye,
    title: 'Vision 模型名单',
    description: '图注看图说话的模型能力探测名单（追加/停用）',
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
    href: '/admin/console/mcp',
    icon: Plug,
    title: 'MCP 配置',
    description: 'MCP server 工具加载（stdio/http/sse）',
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
