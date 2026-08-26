import { describe, expect, it, vi } from "vitest"

import type { Equipment } from "@/lib/mock/types"
import { buildPerformanceAnalysis } from "./metrics"

vi.mock("@/lib/api/client", () => ({
  useApiMode: true,
}))

function truck(overrides: Partial<Equipment> = {}): Equipment {
  return {
    id: "CAM-001",
    code: "CAM-001",
    type: "haul_truck",
    model: "Test",
    state: "mouvement_vide",
    position: { x: 0, y: 0 },
    heading: 0,
    speedKmh: 0,
    fuelPct: 50,
    gasoilLph: null,
    tdPct: null,
    tuPct: null,
    engineOn: true,
    operatorId: null,
    zoneId: null,
    destinationZoneId: null,
    payloadTons: 0,
    capacityTons: 100,
    odometerKm: 0,
    engineHours: 0,
    tripsThisShift: 0,
    waitingMinutesThisShift: 0,
    idleMinutesThisShift: 0,
    lastUpdate: null,
    siteId: "SITE-1",
    healthScore: null,
    cycleActuel: [],
    cycleDureeMoyenneMin: null,
    ...overrides,
  }
}

describe("buildFuel API mode", () => {
  it("does not produce NaN KPI values when litres are unknown", () => {
    const analysis = buildPerformanceAnalysis({
      metric: "fuel",
      equipment: [truck({ gasoilLph: null }), truck({ id: "CAM-002", code: "CAM-002", gasoilLph: 42 })],
      zones: [],
      productionHourly: [],
      downtimeReasons: [],
    })
    for (const kpi of analysis.kpis) {
      expect(kpi.value).not.toMatch(/NaN/)
    }
  })
})

describe("buildVoyages API mode", () => {
  it("does not use capacity*0.88 when payload is unknown", () => {
    const analysis = buildPerformanceAnalysis({
      metric: "voyages",
      equipment: [truck({ tripsThisShift: 3, payloadTons: undefined, capacityTons: 100 })],
      zones: [],
      productionHourly: [],
      downtimeReasons: [],
    })
    const row = analysis.rows[0]
    expect(row?.tons).toBeNull()
  })

  it("does not invent hauled tons from instantaneous payload", () => {
    const analysis = buildPerformanceAnalysis({
      metric: "voyages",
      equipment: [truck({ tripsThisShift: 3, payloadTons: 90, capacityTons: 100 })],
      zones: [],
      productionHourly: [],
      downtimeReasons: [],
    })
    expect(analysis.rows[0]?.tons).toBeNull()
    expect(analysis.rows[0]?.tons).not.toBe(270)
  })

  it("excludes water trucks from haul-truck voyage rows", () => {
    const analysis = buildPerformanceAnalysis({
      metric: "voyages",
      equipment: [
        truck({ tripsThisShift: 2, payloadTons: 80 }),
        truck({ id: "WTR-001", code: "WTR-001", type: "water_truck", tripsThisShift: 9, payloadTons: 40 }),
      ],
      zones: [],
      productionHourly: [],
      downtimeReasons: [],
    })
    expect(analysis.rows.map((r) => r.code)).toEqual(["CAM-001"])
  })
})

describe("buildWaiting API mode", () => {
  it("does not turn current occupancy into historical queue metrics", () => {
    const analysis = buildPerformanceAnalysis({
      metric: "waiting",
      equipment: [truck({ zoneId: "Z1", waitingMinutesThisShift: 40 })],
      zones: [
        {
          id: "Z1",
          name: "Banc B",
          type: "chargement",
          points: [],
          color: "#000",
          description: "",
          capacity: 4,
          siteId: "SITE-1",
        },
      ],
      productionHourly: [],
      downtimeReasons: [],
      siteId: "SITE-1",
    })
    expect(analysis.rows[0]?.trucks).toBe(1)
    expect(analysis.rows[0]?.avgQueue).toBeNull()
    expect(analysis.rows[0]?.maxQueue).toBeNull()
    expect(analysis.rows[0]?.waitMin).toBeNull()
  })
})

describe("buildDowntime API mode", () => {
  it("does not invent Ouvert/Suivi from hours", () => {
    const analysis = buildPerformanceAnalysis({
      metric: "downtime",
      equipment: [truck()],
      zones: [],
      productionHourly: [],
      downtimeReasons: [{ reason: "Arrêt matériel", hours: 5.2 }],
    })
    expect(analysis.rows[0]?.status).toBe("—")
    expect(analysis.rows[0]?.equipment).toBe("—")
  })
})

describe("buildTd / buildTu API mode", () => {
  it("missing TD/TU stays unknown, not 0%", () => {
    const td = buildPerformanceAnalysis({
      metric: "td",
      equipment: [truck({ tdPct: null }), truck({ id: "CAM-002", code: "CAM-002", tdPct: null })],
      zones: [],
      productionHourly: [],
      downtimeReasons: [],
    })
    expect(td.kpis.find((k) => k.id === "td")?.value).toBe("—")
    expect(td.rows[0]?.td).toBeNull()
    expect(td.interpretation.facts.join(" ")).not.toMatch(/~0 %/)

    const tu = buildPerformanceAnalysis({
      metric: "tu",
      equipment: [truck({ tuPct: null })],
      zones: [],
      productionHourly: [],
      downtimeReasons: [],
    })
    expect(tu.kpis.find((k) => k.id === "tu")?.value).toBe("—")
    expect(tu.rows[0]?.tu).toBeNull()
  })
})

describe("buildProduction API mode", () => {
  it("does not coerce missing hourly target to 0", () => {
    const analysis = buildPerformanceAnalysis({
      metric: "production",
      equipment: [truck()],
      zones: [],
      productionHourly: [{ label: "07:00", tonnage: 100, target: null }],
      productionShiftly: [],
      downtimeReasons: [],
    })
    expect(analysis.kpis.find((k) => k.id === "target")?.value).toBe("—")
    expect(analysis.rows[0]?.target).toBe("—")
    expect(analysis.chartData[0]?.target).toBeNull()
    expect(analysis.rows[0]?.trips).toBe("—")
    expect(analysis.rows[0]?.delayMin).toBe("—")
  })
})
