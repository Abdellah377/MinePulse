import type { ReactNode } from "react"
import { cn } from "@/lib/utils"

export function ContextHeader({
  title,
  subtitle,
  meta,
  actions,
  className,
}: {
  title: string
  subtitle?: string
  meta?: string
  actions?: ReactNode
  className?: string
}) {
  return (
    <div className={cn("flex shrink-0 flex-wrap items-end justify-between gap-3", className)}>
      <div>
        <h1 className="text-[15px] font-semibold tracking-tight text-foreground">{title}</h1>
        {subtitle && <p className="text-[12px] text-muted">{subtitle}</p>}
        {meta && <p className="mt-0.5 text-[11px] text-muted-2">{meta}</p>}
      </div>
      {actions}
    </div>
  )
}
