import { cn } from '@/lib/utils'

/**
 * 列表/表单型页面的统一容器。
 * app shell 改为满宽后，非工作区页面靠这个收回到可读宽度。
 */
export function PageShell({
  children,
  className,
  width = 'default',
}: {
  children: React.ReactNode
  className?: string
  width?: 'default' | 'narrow'
}) {
  return (
    <div
      className={cn(
        'mx-auto px-6 py-8',
        width === 'narrow' ? 'max-w-3xl' : 'max-w-6xl',
        className,
      )}
    >
      {children}
    </div>
  )
}

export function PageHeader({
  title,
  description,
  children,
}: {
  title: string
  description?: string
  children?: React.ReactNode
}) {
  return (
    <div className="flex items-start justify-between gap-4 border-b pb-4">
      <div className="space-y-0.5">
        <h1 className="text-xl font-bold tracking-tight">{title}</h1>
        {description && (
          <p className="text-[13px] text-muted-foreground">{description}</p>
        )}
      </div>
      {children && <div className="flex shrink-0 items-center gap-2">{children}</div>}
    </div>
  )
}
