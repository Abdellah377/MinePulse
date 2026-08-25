import { describe, expect, it, vi } from "vitest"

vi.mock("@/lib/api/client", () => ({
  useApiMode: true,
}))

describe("getShiftProduction API contract", () => {
  it("throws in API mode — use shiftProductionRollup instead", async () => {
    const { getShiftProduction } = await import("./scenarioMetrics")
    expect(() => getShiftProduction([])).toThrow(/mock-only/)
  })
})
