import { describe, expect, it } from "vitest"

import type { OptimizationCandidate } from "@/lib/api/types/optimization"
import { visibleOptimizationPlans } from "./optimizationDisplay"

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
