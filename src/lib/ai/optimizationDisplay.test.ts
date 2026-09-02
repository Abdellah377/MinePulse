import { describe, expect, it } from "vitest"

import type { OptimizationCandidate } from "@/lib/api/types/optimization"
import { visibleOptimizationPlans, optimizationImpactPreview, optimizerOperatorStatus, impactMetricTone, impactDelta, formatImpactValue, compactPlanImpact, splitImpactRows, classifyOptimizationImpact, planCandidateLabel } from "./optimizationDisplay"

const candidate = (id: string): OptimizationCandidate => ({
  candidateId: id,
  truckId: 1,
  truckCode: "TRK-1",
  loaderId: 10,
  loaderCode: "LD-1",
  destZoneCode: "D1",
  originZoneCode: "L1",
  roadIds: [],
  distanceKm: 1,
  travelMinutes: 2,
  waitMinutes: 0,
  score: 2,
  constraintNotes: [],
  rankReason: "score",
})

describe("visibleOptimizationPlans", () => {
  it("shows no fake plan when there are zero candidates", () => {
    expect(visibleOptimizationPlans([])).toEqual({ visible: [], hiddenCount: 0 })
    expect(visibleOptimizationPlans(null)).toEqual({ visible: [], hiddenCount: 0 })
  })

  it("displays a single candidate", () => {
    const { visible, hiddenCount } = visibleOptimizationPlans([candidate("c-1")])
    expect(visible.map((row) => row.candidateId)).toEqual(["c-1"])
    expect(hiddenCount).toBe(0)
  })

  it("displays all three when exactly three exist", () => {
    const { visible, hiddenCount } = visibleOptimizationPlans([
      candidate("c-1"),
      candidate("c-2"),
      candidate("c-3"),
    ])
    expect(visible.map((row) => row.candidateId)).toEqual(["c-1", "c-2", "c-3"])
    expect(hiddenCount).toBe(0)
  })

  it("displays only the top three of five and leaves the persisted array untouched", () => {
    const persisted = ["c-1", "c-2", "c-3", "c-4", "c-5"].map(candidate)
    const snapshot = persisted.map((row) => row.candidateId)
    const { visible, hiddenCount } = visibleOptimizationPlans(persisted)
    expect(visible.map((row) => row.candidateId)).toEqual(["c-1", "c-2", "c-3"])
    expect(hiddenCount).toBe(2)
    expect(persisted.map((row) => row.candidateId)).toEqual(snapshot)
    expect(persisted).toHaveLength(5)
  })

  it("keeps the recommended candidate when it is ranked first", () => {
    const persisted = [candidate("c-best"), candidate("c-2"), candidate("c-3"), candidate("c-4")]
    const { visible } = visibleOptimizationPlans(persisted)
    expect(visible[0]?.candidateId).toBe("c-best")
  })
})

describe("optimizationImpactPreview", () => {
  it("compares current vs selected using only known metrics", () => {
    const current = { ...candidate("now"), isCurrent: true, waitMinutes: 20, travelMinutes: 12, distanceKm: 4 }
    const next = { ...candidate("opt"), waitMinutes: 5, travelMinutes: 10, distanceKm: 3.5 }
    const preview = optimizationImpactPreview([current, next], "opt")
    expect(preview?.rows).toEqual([
      { key: "waitMinutes", before: 20, after: 5 },
      { key: "travelMinutes", before: 12, after: 10 },
      { key: "distanceKm", before: 4, after: 3.5 },
      { key: "score", before: 2, after: 2 },
    ])
  })

  it("omits metrics that are unknown on both sides", () => {
    const current = { ...candidate("now"), isCurrent: true, waitMinutes: 8, travelMinutes: null, distanceKm: null, score: null }
    const next = { ...candidate("opt"), waitMinutes: 3, travelMinutes: null, distanceKm: null, score: null }
    const preview = optimizationImpactPreview([current, next], "opt")
    expect(preview?.rows).toEqual([{ key: "waitMinutes", before: 8, after: 3 }])
  })

  it("returns null when nothing can be shown", () => {
    expect(optimizationImpactPreview([], "x")).toBeNull()
    const blank = { ...candidate("now"), isCurrent: true, waitMinutes: null, travelMinutes: null, distanceKm: null, score: null }
    expect(classifyOptimizationImpact([blank], "now").mode).toBe("CURRENT_PLAN_BEST")
  })

  it("treats lower wait/travel/distance/score as improvements and an increase as a trade-off", () => {
    expect(impactMetricTone("waitMinutes", 12, 5)).toBe("better")
    expect(impactMetricTone("travelMinutes", 8.3, 9.1)).toBe("worse")
    expect(impactMetricTone("distanceKm", 4.8, 4.8)).toBe("neutral")
    expect(impactMetricTone("score", 18, 10.4)).toBe("better")
    expect(impactMetricTone("waitMinutes", 12, null)).toBe("unknown")
    expect(impactDelta(9.7, 4.7)).toBe(-5)
  })

  it("does not render a null metric as zero", () => {
    expect(formatImpactValue(null, "min")).toBe("Non disponible")
    expect(formatImpactValue(0, "min")).toBe("0 min")
  })

  it("splits primary wait/travel from secondary distance/score", () => {
    const { primary, secondary } = splitImpactRows([
      { key: "waitMinutes", before: 12, after: 5 },
      { key: "travelMinutes", before: 8, after: 9 },
      { key: "distanceKm", before: 4, after: 3 },
      { key: "score", before: 20, after: 10 },
    ])
    expect(primary.map((row) => row.key)).toEqual(["waitMinutes", "travelMinutes"])
    expect(secondary.map((row) => row.key)).toEqual(["distanceKm", "score"])
  })

  it("builds a compact alternative preview from real values only", () => {
    expect(compactPlanImpact({ ...candidate("alt"), waitMinutes: 5, travelMinutes: 9, score: 14, distanceKm: null })).toEqual([
      { key: "waitMinutes", value: 5, unit: "min" },
      { key: "travelMinutes", value: 9, unit: "min" },
      { key: "score", value: 14, unit: "" },
    ])
    expect(compactPlanImpact({ ...candidate("blank"), waitMinutes: null, travelMinutes: null, score: null })).toEqual([])
  })

  it("does not market zero deltas when the current plan is selected", () => {
    const current = { ...candidate("now"), isCurrent: true, waitMinutes: 2, travelMinutes: 3.9, distanceKm: 2.586, score: 5.9 }
    const alt = { ...candidate("alt"), waitMinutes: 10, travelMinutes: 5, score: 15, isCurrent: false }
    const view = classifyOptimizationImpact([current, alt], "now")
    expect(view.mode).toBe("CURRENT_PLAN_BEST")
    expect(view.rows).toEqual([])
    expect(planCandidateLabel(current, "now", 1)).toBe("Plan actuel · Recommandé")
  })

  it("still hides zero-delta KPIs when the current plan is selected but not uniquely best", () => {
    const current = { ...candidate("now"), isCurrent: true, waitMinutes: 10, travelMinutes: 3.9, distanceKm: 2.586, score: 13.9 }
    const alt = { ...candidate("alt"), waitMinutes: 2, travelMinutes: 5, score: 7, isCurrent: false }
    const view = classifyOptimizationImpact([current, alt], "now")
    expect(view.mode).toBe("CURRENT_SELECTED")
    expect(view.rows).toEqual([])
  })

  it("produces real deltas when a better alternative is selected", () => {
    const current = { ...candidate("now"), isCurrent: true, waitMinutes: 10, travelMinutes: 3.9, distanceKm: 2.586, score: 13.9 }
    const alt = { ...candidate("alt"), waitMinutes: 2, travelMinutes: 5, distanceKm: 3, score: 7, isCurrent: false }
    const view = classifyOptimizationImpact([current, alt], "alt")
    expect(view.mode).toBe("ALTERNATIVE_BETTER")
    expect(view.rows).toEqual([
      { key: "waitMinutes", before: 10, after: 2 },
      { key: "travelMinutes", before: 3.9, after: 5 },
      { key: "distanceKm", before: 2.586, after: 3 },
      { key: "score", before: 13.9, after: 7 },
    ])
  })

  it("keeps real deltas when a comparable (not better) alternative is selected", () => {
    const current = { ...candidate("now"), isCurrent: true, waitMinutes: 2, travelMinutes: 3, distanceKm: 2, score: 5 }
    const alt = { ...candidate("alt"), waitMinutes: 8, travelMinutes: 4, distanceKm: 3, score: 12, isCurrent: false }
    const view = classifyOptimizationImpact([current, alt], "alt")
    expect(view.mode).toBe("ALTERNATIVE_COMPARABLE")
    expect(view.rows.find((row) => row.key === "score")).toEqual({ key: "score", before: 5, after: 12 })
  })

  it("labels unnamed alternatives without moving the current/recommended badges", () => {
    const current = { ...candidate("now"), isCurrent: true }
    const alt = { ...candidate("alt"), isCurrent: false }
    expect(planCandidateLabel(alt, "now", 1)).toBe("Alternative 1")
    expect(planCandidateLabel(current, "now", 1)).toBe("Plan actuel · Recommandé")
  })

  it("shows a single wait reason when a partial alternative is selected", () => {
    const current = { ...candidate("now"), isCurrent: true, waitMinutes: 10, travelMinutes: 3.9, distanceKm: 2.586, score: 13.9 }
    const alt = { ...candidate("alt"), waitMinutes: null, travelMinutes: 3.9, distanceKm: 2.586, score: null, isCurrent: false }
    const view = classifyOptimizationImpact([current, alt], "alt")
    expect(view.mode).toBe("ALTERNATIVES_NOT_EVALUABLE")
    expect(view.reason).toContain("temps d’attente du chargeur indisponible")
    expect(view.rows).toEqual([
      { key: "travelMinutes", before: 3.9, after: 3.9 },
      { key: "distanceKm", before: 2.586, after: 2.586 },
    ])
    expect(view.rows.some((row) => row.key === "waitMinutes")).toBe(false)
  })
})

describe("optimizerOperatorStatus", () => {
  it("uses the precise missingReason instead of the generic fallback", () => {
    expect(
      optimizerOperatorStatus({
        outcome: "INSUFFICIENT_DATA",
        explanation: {
          why: "Données insuffisantes pour évaluer un plan de dispatch (métrique absente ≠ 0).",
          missingReason: "Destination actuelle inconnue",
        },
      }),
    ).toBe("Données insuffisantes pour évaluer un plan de dispatch (Destination actuelle inconnue).")
  })

  it("keeps a precise backend why unchanged", () => {
    expect(
      optimizerOperatorStatus({
        outcome: "INSUFFICIENT_DATA",
        explanation: { why: "Données insuffisantes pour évaluer un plan de dispatch (Temps de trajet indisponible).", missingReason: "Temps de trajet indisponible" },
      }),
    ).toContain("Temps de trajet indisponible")
  })

  it("names an unroutable plan", () => {
    expect(optimizerOperatorStatus({ outcome: "NO_FEASIBLE_PLAN", explanation: { missingReason: "Aucun itinéraire faisable" } })).toBe("Aucun itinéraire faisable")
  })
})
