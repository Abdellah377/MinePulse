import { useState, type ReactNode } from "react"
import { ChevronLeft, ChevronRight, SlidersHorizontal } from "lucide-react"

import { cn } from "@/lib/utils"

/**
 * Narrow, collapsible filter rail for Carte / Film-style supervision panels.
 */
export function FilterDrawer({
  title = "Filtres",
  children,
  defaultCollapsed = false,
  className,
  widthCollapsed = 44,
  widthExpanded = 220,
}: {
  title?: string
  children: ReactNode
  defaultCollapsed?: boolean
  className?: string
  widthCollapsed?: number
  widthExpanded?: number
}) {
  const [collapsed, setCollapsed] = useState(defaultCollapsed)

  return (
    <aside
      className={cn(
        "flex shrink-0 flex-col overflow-hidden border-r border-border bg-surface transition-[width] duration-200",
        className
      )}
      style={{ width: collapsed ? widthCollapsed : widthExpanded }}
    >
      <div className="flex h-9 shrink-0 items-center gap-1 border-b border-border px-1.5">
        <button
          type="button"
          onClick={() => setCollapsed((c) => !c)}
          className="flex size-7 items-center justify-center rounded-lg text-muted hover:bg-surface-2 hover:text-foreground"
          aria-label={collapsed ? "Ouvrir les filtres" : "Réduire les filtres"}
        >
          {collapsed ? <ChevronRight className="size-3.5" /> : <ChevronLeft className="size-3.5" />}
        </button>
        {!collapsed && (
          <span className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-foreground/80">
            <SlidersHorizontal className="size-3" />
            {title}
          </span>
        )}
      </div>
      {!collapsed && <div className="min-h-0 flex-1 overflow-y-auto">{children}</div>}
    </aside>
  )
}
