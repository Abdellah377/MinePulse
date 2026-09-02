import { describe, expect, it } from "vitest"

import type { OptimizationCandidate } from "@/lib/api/types/optimization"
import { visibleOptimizationPlans, optimizationImpactPreview, optimizerOperatorStatus } from "./optimizationDisplay"

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
    ])
  })

  it("omits metrics that are unknown on both sides", () => {
    const current = { ...candidate("now"), isCurrent: true, waitMinutes: 8, travelMinutes: null, distanceKm: null }
    const next = { ...candidate("opt"), waitMinutes: 3, travelMinutes: null, distanceKm: null }
    const preview = optimizationImpactPreview([current, next], "opt")
    expect(preview?.rows).toEqual([{ key: "waitMinutes", before: 8, after: 3 }])
  })

  it("returns null when nothing can be shown", () => {
    expect(optimizationImpactPreview([], "x")).toBeNull()
    const blank = { ...candidate("now"), isCurrent: true, waitMinutes: null, travelMinutes: null, distanceKm: null }
    expect(optimizationImpactPreview([blank], "now")).toBeNull()
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
