'use client'

import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

import { normalizeInlineTables } from '@/lib/normalize-markdown'

/**
 * 统一的 Markdown 渲染器。
 *
 * 关键点：
 * - 挂载 `remark-gfm` 插件，否则 react-markdown 默认只认 CommonMark，
 *   不支持 GFM 表格语法（| a | b |），AI 输出的表格会原样显示成纯文本。
 * - 预处理 `normalizeInlineTables`：把 AI 偶尔输出的单行压缩表格展开成多行。
 *
 * 所有展示 AI 文本的地方（对话气泡、草稿预览、初始化助手）都应使用此组件，
 * 保证表格/删除线/任务列表等 GFM 扩展解析一致。
 */
interface MarkdownProps {
  children: string
  className?: string
}

export function Markdown({ children, className }: MarkdownProps) {
  return (
    <div className={className}>
      <ReactMarkdown remarkPlugins={[remarkGfm]}>
        {normalizeInlineTables(children)}
      </ReactMarkdown>
    </div>
  )
}
