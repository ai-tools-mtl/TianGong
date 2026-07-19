import { redirect } from 'next/navigation'

export default function ContentPage() {
  // Content 域默认落地到 Templates（阶段 2 实现）；占位阶段也走相同 redirect。
  redirect('/admin/content/templates')
}
