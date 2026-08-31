import { expect, it } from "vitest"
import type { RoutePath } from "@/lib/mock/types"
import { canReach, roadStatus, routableEdges } from "./roadNetwork"

function road(overrides: Partial<RoutePath> = {}): RoutePath {
  return {
    id: "R-03",
    fromZoneId: "BANC_A",
    toZoneId: "CRUSHER",
    points: [
      { x: 0, y: 0 },
      { x: 10, y: 10 },
    ],
    distanceKm: 4.2,
    siteId: "MP-SIM-01",
    status: "OPEN",
    speedLimitKmh: 40,
    ...overrides,
  }
}

it("treats missing status as OPEN and keeps optional fields null", () => {
  const unknown = road({ status: undefined, speedLimitKmh: null, description: null, statusReason: null })
  expect(roadStatus(unknown)).toBe("OPEN")
  expect(unknown.speedLimitKmh).toBeNull()
  expect(unknown.description).toBeNull()
})

it("excludes CLOSED roads from routable edges and keeps OPEN and RESTRICTED", () => {
  const edges = routableEdges([
    road({ id: "R-03", status: "CLOSED" }),
    road({ id: "R-05", fromZoneId: "BANC_A", toZoneId: "PARKING", status: "OPEN" }),
    road({ id: "R-06", fromZoneId: "PARKING", toZoneId: "CRUSHER", status: "RESTRICTED" }),
  ])
  expect(edges.map((e) => e.id).sort()).toEqual(["R-05", "R-06"])
  expect(edges.find((e) => e.id === "R-06")?.status).toBe("RESTRICTED")
})

it("canReach uses only routable edges and reports a disconnected network honestly", () => {
  const primary = road({ id: "R-03", status: "CLOSED" })
  const alt = [
    road({ id: "R-05", fromZoneId: "BANC_A", toZoneId: "PARKING", status: "OPEN" }),
    road({ id: "R-06", fromZoneId: "PARKING", toZoneId: "CRUSHER", status: "OPEN" }),
  ]
  expect(canReach("BANC_A", "CRUSHER", [primary])).toBe(false)
  expect(canReach("BANC_A", "CRUSHER", [primary, ...alt])).toBe(true)
  expect(canReach("BANC_A", "DUMP_S", alt)).toBe(false)
})
