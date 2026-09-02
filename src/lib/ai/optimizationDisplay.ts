import type { OptimizationCandidate } from "@/lib/api/types/optimization"

export const VISIBLE_OPTIMIZATION_PLAN_COUNT = 3

export const IMPACT_METRIC_LABEL = {
  waitMinutes: "Attente",
  travelMinutes: "Trajet",
  distanceKm: "Distance",
  score: "Objectif",
} as const

export const IMPACT_METRIC_UNIT = {
  waitMinutes: "min",
  travelMinutes: "min",
  distanceKm: "km",
  score: "",
} as const

export type ImpactMetricKey = keyof typeof IMPACT_METRIC_LABEL

export const PRIMARY_IMPACT_KEYS: ImpactMetricKey[] = ["waitMinutes", "travelMinutes"]
export const SECONDARY_IMPACT_KEYS: ImpactMetricKey[] = ["distanceKm", "score"]

export type ImpactTone = "better" | "worse" | "neutral" | "unknown"

export type ImpactPreviewRow = {
  key: ImpactMetricKey
  before: number | null
  after: number | null
}

export type ImpactComparisonMode =
  | "CURRENT_PLAN_BEST"
  | "CURRENT_SELECTED"
  | "ALTERNATIVE_BETTER"
  | "ALTERNATIVE_COMPARABLE"
  | "ALTERNATIVES_NOT_EVALUABLE"
  | "NO_DATA"

export type OptimizationImpactView = {
  mode: ImpactComparisonMode
  current: OptimizationCandidate | null
  selected: OptimizationCandidate | null
  rows: ImpactPreviewRow[]
  reason: string | null
}

function impactRowsFor(
  current: OptimizationCandidate | null,
  selected: OptimizationCandidate | null,
  { bothSidesOnly = false }: { bothSidesOnly?: boolean } = {},
): ImpactPreviewRow[] {
  const keys = Object.keys(IMPACT_METRIC_LABEL) as ImpactMetricKey[]
  return keys.flatMap((key) => {
    const before = current?.[key] ?? null
    const after = selected?.[key] ?? null
    if (bothSidesOnly) {
      if (before == null || after == null) return []
      return [{ key, before, after }]
    }
    if (before == null && after == null) return []
    return [{ key, before, after }]
  })
}

export function classifyOptimizationImpact(
  candidates: OptimizationCandidate[] | null | undefined,
  selectedCandidateId: string | null | undefined,
): OptimizationImpactView {
  const all = candidates ?? []
  const current = all.find((row) => row.isCurrent) ?? null
  const selected = selectedCandidateId
    ? all.find((row) => row.candidateId === selectedCandidateId) ?? null
    : null
  if (!current && !selected) {
    return { mode: "NO_DATA", current, selected, rows: [], reason: null }
  }
  const scored = all.filter((row) => row.score != null)
  const bestScore = scored.length ? Math.min(...scored.map((row) => row.score as number)) : null
  const currentIsBest = current?.score != null && bestScore != null && current.score === bestScore
  const othersScored = scored.some((row) => !row.isCurrent)

  if (selected?.isCurrent) {
    return {
      mode: currentIsBest || !othersScored ? "CURRENT_PLAN_BEST" : "CURRENT_SELECTED",
      current,
      selected,
      rows: [],
      reason: null,
    }
  }

  if (selected && selected.score == null) {
    const waitMissing = selected.waitMinutes == null
    const reason = waitMissing
      ? "Impact complet non calculable — temps d’attente du chargeur indisponible."
      : selected.travelMinutes == null
        ? "Impact complet non calculable — temps de trajet indisponible."
        : "Impact complet non calculable — score indisponible."
    return {
      mode: "ALTERNATIVES_NOT_EVALUABLE",
      current,
      selected,
      rows: impactRowsFor(current, selected, { bothSidesOnly: true }),
      reason,
    }
  }

  const rows = impactRowsFor(current, selected)
  if (selected && selected.score != null && current?.score != null && selected.score < current.score) {
    return { mode: "ALTERNATIVE_BETTER", current, selected, rows, reason: null }
  }
  if (selected && selected.score != null) {
    return { mode: "ALTERNATIVE_COMPARABLE", current, selected, rows, reason: null }
  }
  if (!rows.length) {
    return { mode: "NO_DATA", current, selected, rows: [], reason: null }
  }
  return { mode: "ALTERNATIVE_COMPARABLE", current, selected, rows, reason: null }
}

export function optimizationImpactPreview(
  candidates: OptimizationCandidate[] | null | undefined,
  selectedCandidateId: string | null | undefined,
) {
  const view = classifyOptimizationImpact(candidates, selectedCandidateId)
  if (view.mode === "NO_DATA" && !view.rows.length) return null
  return { current: view.current, selected: view.selected, rows: view.rows, mode: view.mode, reason: view.reason }
}

const LOWER_IS_BETTER: Record<ImpactMetricKey, boolean> = {
  waitMinutes: true,
  travelMinutes: true,
  distanceKm: true,
  score: true,
}

/** Lower wait, travel, distance, and objective score are improvements. */
export function impactMetricTone(
  key: ImpactMetricKey,
  before: number | null,
  after: number | null,
): ImpactTone {
  if (before == null || after == null) return "unknown"
  if (after === before) return "neutral"
  const improved = LOWER_IS_BETTER[key] ? after < before : after > before
  return improved ? "better" : "worse"
}

export function formatImpactValue(value: number | null, unit: string): string {
  if (value == null) return "Non disponible"
  return unit ? `${value} ${unit}` : String(value)
}

export function impactDelta(before: number | null, after: number | null): number | null {
  if (before == null || after == null) return null
  return Math.round((after - before) * 1000) / 1000
}

export function splitImpactRows(rows: ImpactPreviewRow[]): {
  primary: ImpactPreviewRow[]
  secondary: ImpactPreviewRow[]
} {
  const byKey = new Map(rows.map((row) => [row.key, row]))
  return {
    primary: PRIMARY_IMPACT_KEYS.flatMap((key) => {
      const row = byKey.get(key)
      return row ? [row] : []
    }),
    secondary: SECONDARY_IMPACT_KEYS.flatMap((key) => {
      const row = byKey.get(key)
      return row ? [row] : []
    }),
  }
}

export function compactPlanImpact(plan: Pick<OptimizationCandidate, ImpactMetricKey> | null | undefined) {
  if (!plan) return []
  const keys: ImpactMetricKey[] = ["waitMinutes", "travelMinutes", "score"]
  return keys.flatMap((key) => {
    const value = plan[key]
    if (value == null) return []
    return [{ key, value, unit: IMPACT_METRIC_UNIT[key] }]
  })
}

export function optimizerOperatorStatus(run: {
  outcome?: string | null
  explanation?: { why?: string | null; missingReason?: string | null } | null
}): string {
  const missing = run.explanation?.missingReason?.trim()
  const why = run.explanation?.why?.trim()
  const generic = !why || why.includes("métrique absente")
  if (missing && generic) {
    if (run.outcome === "NO_FEASIBLE_PLAN") return missing
    return `Données insuffisantes pour évaluer un plan de dispatch (${missing}).`
  }
  if (why) return why
  if (run.outcome === "FEASIBLE") return "Plan évalué"
  if (run.outcome === "NO_FEASIBLE_PLAN") return "Aucun itinéraire faisable"
  if (run.outcome === "INSUFFICIENT_DATA") return "Données insuffisantes pour évaluer un plan de dispatch"
  if (run.outcome === "NOT_APPLICABLE") return "Optimisation de dispatch non applicable"
  if (run.outcome === "ERROR") return "Optimiseur en échec"
  return run.outcome ? String(run.outcome) : "Optimisation indisponible"
}

export function visibleOptimizationPlans<T extends Pick<OptimizationCandidate, "candidateId">>(
  candidates: T[] | null | undefined,
): { visible: T[]; hiddenCount: number } {
  const all = candidates ?? []
  return {
    visible: all.slice(0, VISIBLE_OPTIMIZATION_PLAN_COUNT),
    hiddenCount: Math.max(0, all.length - VISIBLE_OPTIMIZATION_PLAN_COUNT),
  }
}

export function planCandidateLabel(
  plan: Pick<OptimizationCandidate, "candidateId" | "isCurrent">,
  recommendedCandidateId: string | null | undefined,
  alternativeIndex: number,
): string {
  const parts: string[] = []
  if (plan.isCurrent) parts.push("Plan actuel")
  if (plan.candidateId === recommendedCandidateId) parts.push("Recommandé")
  if (parts.length) return parts.join(" · ")
  return `Alternative ${alternativeIndex}`
}
