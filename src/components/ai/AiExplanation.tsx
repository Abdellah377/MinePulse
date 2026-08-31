import type { ReactNode } from "react"
import { CircleHelp } from "lucide-react"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

export function AiWhyButton({
  onClick,
  expanded,
  className,
}: {
  onClick: () => void
  expanded?: boolean
  className?: string
}) {
  return (
    <Button
      type="button"
      size="sm"
      variant="outline"
      aria-expanded={expanded}
      className={cn("h-7 gap-1.5 text-[11px]", className)}
      onClick={onClick}
    >
      <CircleHelp className="size-3.5" />
      Pourquoi ?
    </Button>
  )
}

export function AiExplanationPanel({
  open,
  children,
}: {
  open: boolean
  children: ReactNode
}) {
  if (!open) return null
  return (
    <div className="mt-2 space-y-2.5 rounded-md border border-border bg-background px-3 py-2.5">
      <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-2">Pourquoi ?</p>
      {children}
    </div>
  )
}

export function AiExplanationBlock({
  label,
  children,
}: {
  label: string
  children: ReactNode
}) {
  return (
    <div>
      <p className="text-[10px] font-medium text-muted-2">{label}</p>
      <div className="mt-0.5 text-[11px] leading-relaxed text-foreground/90">{children}</div>
    </div>
  )
}
