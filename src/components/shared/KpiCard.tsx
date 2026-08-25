import type { ReactNode } from "react"
import { ArrowDown, ArrowUp, Minus } from "lucide-react"

import { cn } from "@/lib/utils"

export function KpiCard({
  label,
  value,
  unit,
  delta,
  deltaLabel,
  icon,
  tone = "default",
  onClick,
}: {
  label: string
  value: string
  unit?: string
  delta?: number
  deltaLabel?: string
  icon?: ReactNode
  tone?: "default" | "success" | "warning" | "danger"
  onClick?: () => void
}) {
  const toneColor =
    tone === "success"
      ? "text-success"
      : tone === "warning"
        ? "text-warning"
        : tone === "danger"
          ? "text-danger"
          : "text-foreground"

  return (
    <button
      onClick={onClick}
      className={cn(
        "flex flex-col gap-2 rounded-xl border border-border/80 bg-surface p-4 text-left shadow-soft-sm transition-colors",
        onClick && "hover:bg-surface-2"
      )}
    >
      <div className="flex items-center justify-between">
        <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-2">
          {label}
        </span>
        {icon && <span className="text-muted-2">{icon}</span>}
      </div>
      <div className="flex items-baseline gap-1.5">
        <span className={cn("text-2xl font-semibold tabular-nums leading-none", toneColor)}>
          {value}
        </span>
        {unit && <span className="text-xs text-muted-2">{unit}</span>}
      </div>
      {typeof delta === "number" && (
        <div
          className={cn(
            "flex items-center gap-1 text-[11px] font-medium",
            delta > 0 ? "text-success" : delta < 0 ? "text-danger" : "text-muted-2"
          )}
        >
          {delta > 0 ? (
            <ArrowUp className="size-3" />
          ) : delta < 0 ? (
            <ArrowDown className="size-3" />
          ) : (
            <Minus className="size-3" />
          )}
          <span>
            {Math.abs(delta).toFixed(1)}
            {deltaLabel ?? ""}
          </span>
        </div>
      )}
    </button>
  )
}
