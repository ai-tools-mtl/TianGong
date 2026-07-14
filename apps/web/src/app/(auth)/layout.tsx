import { Logo } from '@/components/logo'

/**
 * 认证页双栏：左半屏品牌介绍（PC 充分利用宽度），右半屏表单。
 * 窄屏自动退化为单栏（表单居中）。
 */
export default function AuthLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <div className="grid min-h-screen lg:grid-cols-2">
      {/* 品牌介绍栏 */}
      <aside className="relative hidden flex-col justify-between overflow-hidden bg-primary p-10 text-primary-foreground lg:flex">
        <Logo className="[&_span]:text-primary-foreground [&_.text-muted-foreground]:text-primary-foreground/60" />
        <div className="relative space-y-4">
          <h2 className="text-3xl font-bold leading-tight">
            AI 驱动的<br />专利交底书撰写
          </h2>
          <p className="max-w-md text-[14px] leading-relaxed text-primary-foreground/70">
            从灵感到授权的全生命周期智能体。结构化生成、多维评审、版本追溯——
            把工程师从重复的格式劳动里解放出来。
          </p>
        </div>
        <p className="text-[12px] text-primary-foreground/40">
          © 2026 天工 TianGong
        </p>
        {/* AI 紫光晕，呼应产品身份 */}
        <div
          className="pointer-events-none absolute -right-20 top-1/3 size-80 rounded-full opacity-30 blur-3xl"
          style={{ background: 'radial-gradient(circle, var(--ai), transparent 70%)' }}
        />
      </aside>

      {/* 表单栏 */}
      <main className="flex items-center justify-center bg-background px-6 py-12">
        <div className="w-full max-w-sm">{children}</div>
      </main>
    </div>
  )
}
