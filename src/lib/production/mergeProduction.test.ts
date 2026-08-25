import { describe, expect, it } from "vitest"

import {
  formatPosteBarObjectif,
  formatRollupActual,
  formatRollupAttainment,
  formatRollupTarget,
  shiftProductionRollup,
} from "./mergeProduction"

describe("shiftProductionRollup", () => {
  it("returns null attainment when target is missing — not demo fallback", () => {
    const rollup = shiftProductionRollup({
      hourly: [],
      daily: [],
      shiftly: [{ label: "Matin", tonnage: 1000, target: null }],
    })
    expect(rollup.target).toBeNull()
    expect(rollup.attainmentPct).toBeNull()
    expect(rollup.gapTons).toBeNull()
    expect(rollup.actual).toBe(1000)
  })

  it("empty shiftly → null target/attainment; display is em-dash not 0 t / 0%", () => {
    const rollup = shiftProductionRollup({ hourly: [], daily: [], shiftly: [] })
    expect(rollup.target).toBeNull()
    expect(rollup.attainmentPct).toBeNull()
    expect(rollup.actual).toBeNull()
    expect(formatRollupTarget(rollup)).toBe("—")
    expect(formatRollupActual(rollup)).toBe("—")
    expect(formatRollupAttainment(rollup)).toBe("—")
    expect(formatPosteBarObjectif(rollup)).toBe("—")
    expect(formatRollupTarget(rollup)).not.toMatch(/0 t/)
    expect(formatPosteBarObjectif(rollup)).not.toMatch(/0%/)
  })

  it("uses backend attainmentPct when provided", () => {
    const rollup = shiftProductionRollup({
      hourly: [],
      daily: [],
      shiftly: [
        {
          label: "Matin",
          tonnage: 42000,
          target: 42000,
          attainmentPct: 100,
        },
      ],
    })
    expect(rollup.attainmentPct).toBe(100)
    expect(rollup.target).toBe(42000)
    expect(formatRollupTarget(rollup)).not.toBe("—")
    expect(formatRollupTarget(rollup)).toMatch(/t\s*$/)
    expect(formatRollupAttainment(rollup)).toBe("100 %")
    expect(formatPosteBarObjectif(rollup)).toBe("100% objectif")
  })

  it("does not recompute attainment when the backend omitted it", () => {
    const rollup = shiftProductionRollup({
      hourly: [],
      daily: [],
      shiftly: [{ label: "Matin", tonnage: 21000, target: 42000 }],
    })
    expect(rollup.attainmentPct).toBeNull()
    expect(rollup.gapTons).toBeNull()
    expect(formatRollupAttainment(rollup)).toBe("—")
    expect(formatPosteBarObjectif(rollup)).toBe("—")
  })
})
