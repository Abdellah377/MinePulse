import type { OptimizationCandidate } from "@/lib/api/types/optimization"

export const VISIBLE_OPTIMIZATION_PLAN_COUNT = 3

export function visibleOptimizationPlans<T extends Pick<OptimizationCandidate, "candidateId">>(
  candidates: T[] | null | undefined,
): { visible: T[]; hiddenCount: number } {
  const all = candidates ?? []
  return {
    visible: all.slice(0, VISIBLE_OPTIMIZATION_PLAN_COUNT),
    hiddenCount: Math.max(0, all.length - VISIBLE_OPTIMIZATION_PLAN_COUNT),
  }
}
