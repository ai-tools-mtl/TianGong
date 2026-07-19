import { redirect } from 'next/navigation'

export default function ConsolePage() {
  // Console 域默认落地到 LLM 配置页。
  redirect('/admin/console/llm')
}
