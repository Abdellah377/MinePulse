import { ArrowDown, ArrowUp, Minus } from "lucide-react"
import type { ReactNode } from "react"

import {
  IMPACT_METRIC_LABEL,
  IMPACT_METRIC_UNIT,
  compactPlanImpact,
  formatImpactValue,
  impactDelta,
  impactMetricTone,
  splitImpactRows,
  type ImpactPreviewRow,
  type ImpactTone,
  type OptimizationImpactView,
} from "@/lib/ai/optimizationDisplay"
import type { OptimizationCandidate } from "@/lib/api/types/optimization"
import { cn } from "@/lib/utils"

const TONE_LABEL: Record<ImpactTone, string> = {
  better: "amélioration",
  worse: "dégradation",
  neutral: "inchangé",
  unknown: "non comparé",
}

function toneClass(tone: ImpactTone): string {
  if (tone === "better") return "text-accent"
  if (tone === "worse") return "text-warning"
  if (tone === "unknown") return "text-muted"
  return "text-foreground"
}

function MetricTile({ row, compact = false }: { row: ImpactPreviewRow; compact?: boolean }) {
  const tone = impactMetricTone(row.key, row.before, row.after)
  const unit = IMPACT_METRIC_UNIT[row.key]
  const delta = impactDelta(row.before, row.after)
  const hasBeforeAfter = row.before != null && row.after != null
  const ToneIcon = tone === "better" ? ArrowDown : tone === "worse" ? ArrowUp : Minus

  return (
    <div
      className={cn(
        "min-w-0 rounded-md px-2.5 py-2",
        tone === "better" && "bg-accent-soft",
        tone === "worse" && "bg-warning/10",
        (tone === "neutral" || tone === "unknown") && "bg-surface-2/80",
      )}
    >
      <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-2">
        {IMPACT_METRIC_LABEL[row.key]}
      </p>
      {hasBeforeAfter ? (
        <>
          <p className="mt-1 flex min-w-0 flex-wrap items-baseline gap-x-1 gap-y-0.5 text-[12px]">
            <span className="tabular-nums text-muted">{formatImpactValue(row.before, unit)}</span>
            <span className="text-muted-2" aria-hidden="true">
              →
            </span>
            <span className={cn("tabular-nums font-semibold text-foreground", compact ? "text-[13px]" : "text-[15px]")}>
              {formatImpactValue(row.after, unit)}
            </span>
          </p>
          {tone !== "neutral" && (
            <p className={cn("mt-0.5 flex items-center gap-0.5 text-[11px] font-medium", toneClass(tone))}>
              <ToneIcon className="size-3 shrink-0" aria-hidden="true" />
              <span className="tabular-nums">
                {delta == null ? "" : `${delta > 0 ? "+" : ""}${delta}${unit ? ` ${unit}` : ""}`}
              </span>
              <span className="sr-only">{TONE_LABEL[tone]}</span>
            </p>
          )}
        </>
      ) : (
        <p className={cn("mt-1 font-semibold tabular-nums", compact ? "text-[13px]" : "text-[15px]", row.after == null ? "text-muted" : "text-foreground")}>
          {formatImpactValue(row.after, unit)}
        </p>
      )}
    </div>
  )
}

function ImpactShell({
  children,
  muted,
}: {
  children: ReactNode
  muted?: boolean
}) {
  return (
    <section
      data-testid="impact-estime"
      aria-labelledby="impact-estime-title"
      className={cn(
        "min-w-0 rounded-md border px-3.5 py-3",
        muted ? "border-border bg-surface" : "border-accent/35 bg-accent-soft/40",
      )}
    >
      <h2
        id="impact-estime-title"
        className={cn("text-[11px] font-semibold uppercase tracking-wide", muted ? "text-muted-2" : "text-accent")}
      >
        Impact estimé
      </h2>
      {children}
    </section>
  )
}

export function OptimizationImpactCard({
  view,
}: {
  view: OptimizationImpactView | null | undefined
}) {
  if (!view || view.mode === "NO_DATA") {
    return (
      <ImpactShell muted>
        <p className="mt-1.5 text-[12px] text-muted">Non disponible — l’optimiseur n’a pas fourni de métriques comparables.</p>
      </ImpactShell>
    )
  }

  if (view.mode === "CURRENT_PLAN_BEST" || view.mode === "CURRENT_SELECTED") {
    const items = compactPlanImpact(view.selected ?? view.current)
    return (
      <ImpactShell muted>
        <p className="mt-1.5 text-[13px] font-medium text-foreground">Plan actuel sélectionné</p>
        {view.mode === "CURRENT_PLAN_BEST" && (
          <p className="mt-1 text-[12px] text-muted">Le plan actuel reste le meilleur parmi les options évaluables.</p>
        )}
        {items.length > 0 && (
          <p className="mt-2 flex min-w-0 flex-wrap gap-x-2 gap-y-0.5 text-[11px] text-muted">
            {items.map((item) => (
              <span key={item.key} className="min-w-0 whitespace-nowrap">
                {IMPACT_METRIC_LABEL[item.key]}:{" "}
                <span className="tabular-nums text-foreground">{item.unit ? `${item.value} ${item.unit}` : item.value}</span>
              </span>
            ))}
          </p>
        )}
      </ImpactShell>
    )
  }

  const { primary, secondary } = splitImpactRows(view.rows)
  const showGrid = view.mode === "ALTERNATIVE_BETTER" || view.mode === "ALTERNATIVE_COMPARABLE"

  return (
    <ImpactShell muted={!showGrid}>
      {showGrid && <p className="mt-0.5 text-[10px] text-muted-2">Données calculées par l’optimiseur · plan actuel → plan sélectionné</p>}
      {view.reason && <p className="mt-1.5 text-[12px] text-muted">{view.reason}</p>}
      {primary.length > 0 && (
        <div className="mt-2 grid min-w-0 grid-cols-1 gap-2 min-[360px]:grid-cols-2">
          {primary.map((row) => (
            <MetricTile key={row.key} row={row} />
          ))}
        </div>
      )}
      {showGrid && secondary.length > 0 && (
        <div className="mt-2 grid min-w-0 grid-cols-1 gap-2 min-[360px]:grid-cols-2">
          {secondary.map((row) => (
            <MetricTile key={row.key} row={row} compact />
          ))}
        </div>
      )}
    </ImpactShell>
  )
}

export function CompactPlanImpact({ plan }: { plan: OptimizationCandidate }) {
  const items = compactPlanImpact(plan)
  if (!items.length) return null
  return (
    <p data-testid="plan-impact-compact" className="mt-1 flex min-w-0 flex-wrap gap-x-2 gap-y-0.5 text-[11px] text-muted">
      {items.map((item) => (
        <span key={item.key} className="min-w-0 whitespace-nowrap">
          {IMPACT_METRIC_LABEL[item.key]}:{" "}
          <span className="tabular-nums text-foreground">
            {item.unit ? `${item.value} ${item.unit}` : item.value}
          </span>
        </span>
      ))}
    </p>
  )
}
