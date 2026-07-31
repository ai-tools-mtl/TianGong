/**
 * Agent 工具的展示元数据：中文名 + 图标 + 简短描述。
 *
 * agent 可调用的工具见后端 app/ai/tools.py（rag_search / save_memory）+
 * 动态加载的 MCP 工具（名字由 server 决定）。未知工具走兜底映射，
 * 直接展示工具名本身（不破坏，只是不够友好）。
 *
 * 命名按工具的「动作意图」而非实现——用户看到的是「检索知识库」而非「rag_search」。
 */

import { BookSearch, Brain, Lightbulb, Wrench, type LucideIcon } from 'lucide-react'

export interface ToolDisplayMeta {
  /** 中文友好名 */
  label: string
  /** 图标 */
  icon: LucideIcon
  /** 进行中态文案（如"检索知识库中…"） */
  progress: string
  /** 从 args 摘取一句给人看的关键参数（如 query 文本），无则 undefined */
  summarizeArgs?: (args: Record<string, unknown>) => string | undefined
  /** 从 result 摘要一句（如"找到 3 条"），无则 undefined */
  summarizeResult?: (result: string) => string | undefined
}

const KNOWN: Record<string, ToolDisplayMeta> = {
  rag_search: {
    label: '检索知识库',
    icon: BookSearch,
    progress: '检索知识库中…',
    summarizeArgs: (a) => (typeof a.query === 'string' ? `"${a.query.slice(0, 40)}"` : undefined),
    // result 是 str([{content,...}]) 截断——尝试数 content 段落数粗估命中条数
    summarizeResult: (r) => {
      const hits = (r.match(/'content'/g) || []).length
      return hits > 0 ? `找到 ${hits} 条相关片段` : undefined
    },
  },
  save_memory: {
    label: '记忆',
    icon: Brain,
    progress: '记住这条信息…',
    summarizeArgs: (a) => (typeof a.content === 'string' ? a.content.slice(0, 40) : undefined),
    summarizeResult: () => '已记住',
  },
}

const FALLBACK: ToolDisplayMeta = {
  label: '',
  icon: Wrench,
  progress: '执行中…',
}

/** 工具名 → 展示元数据。未知工具返回带原名的兜底。 */
export function getToolMeta(name: string): ToolDisplayMeta {
  const known = KNOWN[name]
  if (known) return known
  // MCP/未知工具：把下划线/连字符转空格做轻度友好化，其余原样
  return {
    ...FALLBACK,
    label: name.replace(/[_-]/g, ' '),
    progress: `${name} 执行中…`,
  }
}

/** 给思考块用的图标（与工具区分）。 */
export const ThinkingIcon = Lightbulb
