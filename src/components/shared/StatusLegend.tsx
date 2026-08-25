import { FILM_STATE_GROUP_LABEL, type FilmStateGroup } from "@/lib/mock/types"
import { FILM_GROUP_CONFIG } from "@/lib/status"
import { cn } from "@/lib/utils"

const ALL_GROUPS = Object.keys(FILM_STATE_GROUP_LABEL) as FilmStateGroup[]

export function StatusLegend({
  groups = ALL_GROUPS,
  compact = false,
  className,
}: {
  groups?: FilmStateGroup[]
  compact?: boolean
  className?: string
}) {
  return (
    <div
      className={cn(
        "flex flex-wrap items-center gap-x-3 gap-y-1",
        compact ? "text-[10px]" : "text-[11px]",
        className
      )}
    >
      <span className="font-semibold uppercase tracking-wider text-muted-2">Légende</span>
      {groups.map((g) => {
        const cfg = FILM_GROUP_CONFIG[g]
        return (
          <span key={g} className="flex items-center gap-1.5 text-muted">
            <span className={cn("size-2.5 shrink-0", cfg.dot)} />
            {cfg.label}
          </span>
        )
      })}
    </div>
  )
}
