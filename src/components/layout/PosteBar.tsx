import { useMemo } from "react"

import { cn } from "@/lib/utils"
import { useApiMode } from "@/lib/api/client"
import { getShiftAttainment } from "@/lib/mock/scenarioMetrics"
import { shiftProductionRollup, formatPosteBarObjectif } from "@/lib/production/mergeProduction"
import { shiftRemainingMinutes } from "@/lib/ops/shiftWindow"
import { useOpsStore } from "@/lib/store/useOpsStore"

export function PosteBar() {
  const shifts = useOpsStore((s) => s.shifts)
  const selectedShiftId = useOpsStore((s) => s.selectedShiftId)
  const alerts = useOpsStore((s) => s.alerts)
  const productionByShift = useOpsStore((s) => s.productionByShift)
  const simNowIso = useOpsStore((s) => s.simNowIso)

  const rollup = useMemo(
    () =>
      shiftProductionRollup({
        hourly: productionByShift.hourly ?? [],
        daily: productionByShift.daily ?? [],
        shiftly: productionByShift.shiftly ?? [],
      }),
    [productionByShift]
  )
  const attainmentPct = useMemo(() => {
    if (useApiMode) return rollup.attainmentPct
    return getShiftAttainment(undefined, productionByShift?.hourly).attainmentPct
  }, [productionByShift, rollup])

  const shift = shifts.find((s) => s.id === selectedShiftId) ?? (useApiMode ? undefined : shifts[0])
  if (!shift) {
    return (
      <div className="mx-4 mb-1 flex h-9 shrink-0 items-center gap-4 rounded-md border border-border/80 bg-surface px-4 text-[11px] text-muted">
        Chargement du poste…
      </div>
    )
  }

  const remainingMin = shiftRemainingMinutes(simNowIso, shift)
  const criticalCount = alerts.filter((a) => a.status !== "resolved" && a.severity === "critical").length
  const h = Math.floor(remainingMin / 60)
  const m = remainingMin % 60

  return (
    <div className="mx-4 mb-1 flex h-9 shrink-0 items-center gap-4 rounded-md border border-border/80 bg-surface px-4 text-[11px]">
      <span className="font-semibold text-foreground/90">{shift.name}</span>
      <span className="text-muted">
        {Number.isFinite(remainingMin) ? `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")} restant` : "Temps restant indisponible"}
      </span>
      <span
        className={cn(
          "rounded-full px-2 py-0.5 font-medium",
          useApiMode || attainmentPct == null
            ? "text-muted"
            : attainmentPct >= 100
              ? "bg-success/10 text-success"
              : attainmentPct >= 90
                ? "bg-warning/10 text-warning"
                : "bg-danger/10 text-danger"
        )}
      >
        {useApiMode
          ? formatPosteBarObjectif(rollup)
          : `${Number(attainmentPct).toFixed(0)}% objectif`}
      </span>
      {criticalCount > 0 && (
        <span className="flex items-center gap-1.5 font-medium text-severity-critical">
          <span className="size-1.5 rounded-full bg-severity-critical" />
          {criticalCount} critique{criticalCount > 1 ? "s" : ""}
        </span>
      )}
    </div>
  )
}
