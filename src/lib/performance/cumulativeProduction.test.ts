import { describe, expect, it } from "vitest"

import {
  buildCumulativeProductionSeries,
  formatPaceGap,
  paceGapMinutes,
  parseShiftEndHour,
  productionPaceStatus,
  remainingShiftHours,
} from "./cumulativeProduction"

describe("buildCumulativeProductionSeries", () => {
  it("sums hourly tonnes so a slowing rate still shows rising cumulative production", () => {
    const { points, projectionKind, projectedEos } = buildCumulativeProductionSeries(
      [
        { label: "06:00", tonnage: 1000, target: 1020 },
        { label: "07:00", tonnage: 900, target: 1020 },
        { label: "08:00", tonnage: 700, target: 1020 },
      ],
      { shiftEndHour: 14 },
    )
    const measured = points.filter((row) => !row.isProjection)
    expect(measured.map((row) => row.actual)).toEqual([1000, 1900, 2600])
    expect(measured[0]?.target).toBe(1020)
    expect(measured[2]?.target).toBe(3060)
    expect(measured[2]?.actual).toBeGreaterThan(measured[1]?.actual as number)
    expect(projectionKind).toBe("pace")
    expect(projectedEos).toBe(Math.round(2600 + (2600 / 3) * 5))
    expect(points.filter((row) => row.isProjection)).toHaveLength(5)
  })

  it("does not treat a missing hourly target as zero", () => {
    const { points, lastTargetCum } = buildCumulativeProductionSeries(
      [{ label: "07:00", tonnage: 100, target: null }],
      { shiftEndHour: 14 },
    )
    expect(points[0]?.target).toBeNull()
    expect(lastTargetCum).toBeNull()
  })

  it("does not invent a projection when the shift end is unknown", () => {
    const series = buildCumulativeProductionSeries(
      [
        { label: "06:00", tonnage: 900, target: 1020 },
        { label: "07:00", tonnage: 880, target: 1020 },
      ],
      { shiftEndHour: null },
    )
    expect(series.projectionKind).toBe("unavailable")
    expect(series.projectedEos).toBeNull()
    expect(series.points.every((row) => row.projected == null)).toBe(true)
  })

  it("treats a fully measured shift as the real end-of-shift outcome, not a forecast", () => {
    const hourly = Array.from({ length: 8 }, (_, i) => ({
      label: `${String(6 + i).padStart(2, "0")}:00`,
      tonnage: 900,
      target: 1020,
    }))
    const series = buildCumulativeProductionSeries(hourly, { shiftEndHour: 14 })
    expect(series.remainingHours).toBe(0)
    expect(series.projectionKind).toBe("measured")
    expect(series.projectedEos).toBe(7200)
    expect(series.points.some((row) => row.isProjection)).toBe(false)
  })
})

describe("production pace status and gap", () => {
  it("labels behind / close / ahead from cumulative actual vs target", () => {
    expect(productionPaceStatus(7000, 8000)).toBe("behind")
    expect(productionPaceStatus(7900, 8000)).toBe("on_track")
    expect(productionPaceStatus(8100, 8000)).toBe("ahead")
    expect(productionPaceStatus(7000, null)).toBe("unknown")
  })

  it("expresses the gap in minutes at the observed pace without inventing a recovery", () => {
    expect(paceGapMinutes(4000, 5000, 5)).toBe(75)
    expect(formatPaceGap(75)).toBe("Retard 75 min")
    expect(formatPaceGap(-20)).toBe("Avance 20 min")
    expect(paceGapMinutes(4000, null, 5)).toBeNull()
  })
})

describe("shift window parsing", () => {
  it("reads remaining hours from the last bucket and shift end", () => {
    expect(parseShiftEndHour("Poste matin 06:00–14:00")).toBe(14)
    expect(
      remainingShiftHours(
        [
          { label: "06:00", tonnage: 1, target: 1 },
          { label: "10:00", tonnage: 1, target: 1 },
        ],
        14,
      ),
    ).toBe(3)
  })
})
