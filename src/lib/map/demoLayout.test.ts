import { expect, it } from "vitest"
import { buildDemoRoutes } from "./demoLayout"
import { canReach } from "./roadNetwork"
import type { Zone } from "@/lib/mock/types"

function box(id: string, type: Zone["type"], x: number, y: number): Zone {
  return {
    id,
    name: id,
    type,
    points: [
      { x: x - 10, y: y - 10 },
      { x: x + 10, y: y - 10 },
      { x: x + 10, y: y + 10 },
      { x: x - 10, y: y + 10 },
    ],
    color: "#000",
    description: "context",
    capacity: 2,
    siteId: "site-khouribga",
  }
}

const zones: Zone[] = [
  box("load-a", "chargement", 100, 100),
  box("load-b", "chargement", 120, 400),
  box("crusher", "concasseur", 700, 120),
  box("dump", "dechargement", 800, 400),
  box("parking", "parking", 300, 500),
  box("fuel", "fuel", 500, 60),
  box("workshop", "atelier", 500, 520),
  box("restricted", "restreinte", 900, 260),
]

it("same zones produce an identical haul layout", () => {
  expect(buildDemoRoutes("site-khouribga", zones)).toEqual(buildDemoRoutes("site-khouribga", zones))
})

it("includes operational connections and an alternate BANC_A to crusher path", () => {
  const routes = buildDemoRoutes("site-khouribga", zones)
  expect(routes.some((r) => r.fromZoneId === "load-a" && r.toZoneId === "crusher")).toBe(true)
  expect(routes.some((r) => r.fromZoneId === "load-a" && r.toZoneId === "parking")).toBe(true)
  expect(routes.some((r) => r.fromZoneId === "parking" && r.toZoneId === "crusher")).toBe(true)
  const closedPrimary = routes.map((r) =>
    r.fromZoneId === "load-a" && r.toZoneId === "crusher" ? { ...r, status: "CLOSED" as const } : r
  )
  expect(canReach("load-a", "crusher", closedPrimary)).toBe(true)
  expect(routes.every((r) => r.status === "OPEN")).toBe(true)
  expect(routes.some((r) => r.speedLimitKmh == null)).toBe(false)
  const alt = routes.filter(
    (r) =>
      (r.fromZoneId === "load-a" && r.toZoneId === "parking") ||
      (r.fromZoneId === "parking" && r.toZoneId === "crusher")
  )
  expect(alt.every((r) => r.points.length >= 4)).toBe(true)
})
