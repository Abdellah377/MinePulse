import type { CycleStage } from "@/lib/mock/types"
import { CYCLE_STAGE_LABEL, cycleTotalMinutes } from "@/lib/mock/types"
import { formatHm } from "@/lib/format"
import { cn } from "@/lib/utils"

/** "Cycle actuel" cells — green OK, amber/red outlier, dash when empty. */
export function CycleStepper({
  stages,
  dureeMoyenneMin,
  className,
}: {
  stages: CycleStage[]
  dureeMoyenneMin: number | null
  className?: string
}) {
  const total = cycleTotalMinutes(stages)
  const avg = dureeMoyenneMin ?? 0
  const aboveAverage = avg > 0 && total > avg * 1.1
  const avgPerStage = avg > 0 ? avg / Math.max(1, stages.length) : 0

  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      <div className="grid grid-cols-6 gap-px overflow-hidden border border-border bg-border">
        {stages.map((stage) => {
          const empty = stage.minutes == null
          return (
            <div
              key={stage.key}
              className={cn(
                "flex min-h-[52px] flex-col items-center justify-center gap-0.5 px-1.5 py-1.5 text-center",
                empty && "bg-surface text-muted-2",
                !empty && !stage.isOutlier && "bg-accent-soft",
                stage.isOutlier && "bg-warning/15 ring-1 ring-inset ring-danger",
                stage.isCurrent && !stage.isOutlier && "ring-1 ring-inset ring-accent"
              )}
            >
              <p className="truncate text-[9px] font-semibold uppercase tracking-wide text-muted">
                {CYCLE_STAGE_LABEL[stage.key]}
              </p>
              <p
                className={cn(
                  "font-mono text-[13px] font-semibold tabular-nums leading-none",
                  empty && "text-muted-2",
                  stage.isOutlier && "text-danger",
                  !empty && !stage.isOutlier && "text-foreground"
                )}
              >
                {empty ? "--:--" : formatHm(stage.minutes!)}
              </p>
              {!empty && avgPerStage > 0 && (
                <p className="font-mono text-[9px] tabular-nums text-muted-2">
                  ({formatHm(avgPerStage)})
                </p>
              )}
            </div>
          )
        })}
      </div>
      <div className="flex items-center justify-between text-[11px] text-muted">
        <span>
          Total cycle :{" "}
          <strong className="font-mono tabular-nums text-foreground">{formatHm(total)}</strong>
          {" · "}
          moy. <span className="font-mono tabular-nums">{dureeMoyenneMin != null ? formatHm(dureeMoyenneMin) : "—"}</span>
        </span>
        {aboveAverage && (
          <span className="font-medium text-danger">↑ au-dessus de la moyenne</span>
        )}
      </div>
    </div>
  )
}
