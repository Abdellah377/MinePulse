import type { RoutePath, Vec2, Zone } from "@/lib/mock/types"

function zoneCenter(points: Vec2[]): Vec2 {
  const n = points.length
  return points.reduce(
    (acc, p) => ({ x: acc.x + p.x / n, y: acc.y + p.y / n }),
    { x: 0, y: 0 }
  )
}

function via(from: Vec2, to: Vec2, t = 0.5, dx = 0, dy = 0): Vec2 {
  return { x: from.x + (to.x - from.x) * t + dx, y: from.y + (to.y - from.y) * t + dy }
}

/** Deterministic mock haul network. Never used when VITE_USE_API is true. */
export function buildDemoRoutes(siteId: string, zones: Zone[]): RoutePath[] {
  const byType = (type: Zone["type"], index = 0) => zones.filter((z) => z.type === type)[index]
  const loadA = byType("chargement", 0)
  const loadB = byType("chargement", 1) ?? loadA
  const crusher = byType("concasseur")
  const dump = byType("dechargement")
  const parking = byType("parking")
  const fuel = byType("fuel")
  const workshop = byType("atelier")
  if (!loadA || !crusher || !dump || !parking) return []

  const centers = Object.fromEntries(zones.map((z) => [z.id, zoneCenter(z.points)]))
  const link = (
    from: Zone,
    to: Zone,
    id: string,
    name: string,
    distanceKm: number,
    extra?: Partial<RoutePath>
  ): RoutePath => {
    const a = centers[from.id]
    const b = centers[to.id]
    return {
      id,
      name,
      fromZoneId: from.id,
      toZoneId: to.id,
      points: [a, via(a, b), b],
      distanceKm,
      siteId,
      status: "OPEN",
      speedLimitKmh: 40,
      description: null,
      statusReason: null,
      statusNote: null,
      ...extra,
    }
  }

  const routes: RoutePath[] = [
    link(loadA, crusher, `${siteId}-RD-BA-CR`, "R-03 Chargement A — Concasseur", 4.2),
    link(loadA, parking, `${siteId}-R-05`, "R-05 Chargement A — Parking", 3.4),
    link(parking, crusher, `${siteId}-R-06`, "R-06 Parking — Concasseur", 2.8),
    link(loadA, dump, `${siteId}-r3`, "R-07 Chargement A — Dump", 3.1),
  ]
  if (loadB && loadB.id !== loadA.id) {
    routes.push(link(loadB, dump, `${siteId}-r2`, "R-08 Chargement B — Dump", 2.6))
    routes.push(link(loadB, crusher, `${siteId}-r4`, "R-04 Chargement B — Concasseur", 3.8))
  }
  if (fuel) routes.push(link(loadA, fuel, `${siteId}-fuel`, "R-10 Chargement A — Fuel", 1.8, { speedLimitKmh: 35 }))
  if (workshop) routes.push(link(loadA, workshop, `${siteId}-ws`, "R-12 Chargement A — Atelier", 2.1, { speedLimitKmh: 32 }))
  return routes
}
