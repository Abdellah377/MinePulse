import { describe, expect, it, vi } from "vitest"

import { dispatchOptimizationBundle } from "./dispatch"

vi.mock("@/lib/api/client", () => ({
  useApiMode: true,
}))

describe("dispatchOptimizationBundle API mode", () => {
  it("preserves null target and attainment — never 0", () => {
    const bundle = dispatchOptimizationBundle(
      "SITE-1",
      [],
      [],
      { hourly: [], daily: [], shiftly: [] },
      15
    )
    expect(bundle.objective.target).toBeNull()
    expect(bundle.objective.attainmentPct).toBeNull()
    expect(bundle.objective.tonnage).toBeNull()
    expect(bundle.baseline.attainmentPct).toBeNull()
    expect(bundle.recommendations).toEqual([])
  })

  it("agrees with a real shiftly target of 42000", () => {
    const bundle = dispatchOptimizationBundle(
      "SITE-1",
      [],
      [],
      {
        hourly: [],
        daily: [],
        shiftly: [{ label: "Matin", tonnage: 38000, target: 42000, attainmentPct: 90.5 }],
      },
      15
    )
    expect(bundle.objective.target).toBe(42000)
    expect(bundle.objective.attainmentPct).toBe(90.5)
    expect(bundle.objective.tonnage).toBe(38000)
    expect(bundle.recommendations).toEqual([])
  })
})
