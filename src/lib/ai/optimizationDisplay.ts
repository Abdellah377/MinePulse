import type { OptimizationCandidate } from "@/lib/api/types/optimization"

export const VISIBLE_OPTIMIZATION_PLAN_COUNT = 3

export const IMPACT_METRIC_LABEL = {
  waitMinutes: "Attente",
  travelMinutes: "Trajet",
  distanceKm: "Distance",
} as const

export const IMPACT_METRIC_UNIT = {
  waitMinutes: "min",
  travelMinutes: "min",
  distanceKm: "km",
} as const

export type ImpactMetricKey = keyof typeof IMPACT_METRIC_LABEL

export function optimizationImpactPreview(
  candidates: OptimizationCandidate[] | null | undefined,
  selectedCandidateId: string | null | undefined,
) {
  const all = candidates ?? []
  const current = all.find((row) => row.isCurrent) ?? null
  const selected = selectedCandidateId
    ? all.find((row) => row.candidateId === selectedCandidateId) ?? null
    : null
  if (!current && !selected) return null
  const keys = Object.keys(IMPACT_METRIC_LABEL) as ImpactMetricKey[]
  const rows = keys.flatMap((key) => {
    const before = current?.[key] ?? null
    const after = selected?.[key] ?? null
    if (before == null && after == null) return []
    return [{ key, before, after }]
  })
  if (!rows.length) return null
  return { current, selected, rows }
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
