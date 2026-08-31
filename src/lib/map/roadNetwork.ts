import type { RoutePath } from "@/lib/mock/types"

export type RoadStatus = "OPEN" | "CLOSED" | "RESTRICTED"
export type RoadOperationalStatus = RoadStatus | "UNKNOWN"

export type RoadStatusReason =
  | "BLASTING"
  | "MAINTENANCE"
  | "ROAD_DAMAGE"
  | "FLOODING"
  | "CONGESTION_CONTROL"
  | "OTHER"

export const ROAD_STATUS_LABEL: Record<RoadOperationalStatus, string> = {
  OPEN: "Ouverte",
  CLOSED: "Fermée",
  RESTRICTED: "Restreinte",
  UNKNOWN: "Statut inconnu",
}

export const ROAD_STATUS_REASON_LABEL: Record<RoadStatusReason, string> = {
  BLASTING: "Préparation de tir",
  MAINTENANCE: "Maintenance",
  ROAD_DAMAGE: "Dégradation de la piste",
  FLOODING: "Inondation",
  CONGESTION_CONTROL: "Régulation de congestion",
  OTHER: "Autre",
}

export const KNOWN_ROAD_STATUSES: RoadStatus[] = ["OPEN", "CLOSED", "RESTRICTED"]

export function roadStatus(route: Pick<RoutePath, "status"> | { status?: string | null }): RoadOperationalStatus {
  const status = route.status
  if (status === "OPEN" || status === "CLOSED" || status === "RESTRICTED") return status
  return "UNKNOWN"
}

export function isRoutableStatus(status: RoadOperationalStatus): status is Extract<RoadOperationalStatus, "OPEN" | "RESTRICTED"> {
  return status === "OPEN" || status === "RESTRICTED"
}

export type RoutableEdge = {
  id: string
  fromZoneId: string
  toZoneId: string
  status: RoadStatus
  distanceKm: number | null
  speedLimitKmh: number | null
}

/** Future routers MUST use this selector. CLOSED and UNKNOWN are never eligible. */
export function routableEdges(roads: RoutePath[]): RoutableEdge[] {
  return roads.flatMap((road) => {
    const status = roadStatus(road)
    if (!isRoutableStatus(status) || !road.fromZoneId || !road.toZoneId) return []
    return [
      {
        id: road.id,
        fromZoneId: road.fromZoneId,
        toZoneId: road.toZoneId,
        status,
        distanceKm: road.distanceKm,
        speedLimitKmh: road.speedLimitKmh ?? null,
      },
    ]
  })
}

export function canReach(fromZoneId: string, toZoneId: string, roads: RoutePath[]): boolean {
  if (fromZoneId === toZoneId) return true
  const adjacency = new Map<string, string[]>()
  for (const edge of routableEdges(roads)) {
    const next = adjacency.get(edge.fromZoneId) ?? []
    next.push(edge.toZoneId)
    adjacency.set(edge.fromZoneId, next)
  }
  const seen = new Set<string>([fromZoneId])
  const queue = [fromZoneId]
  while (queue.length > 0) {
    const current = queue.shift() as string
    for (const next of adjacency.get(current) ?? []) {
      if (seen.has(next)) continue
      if (next === toZoneId) return true
      seen.add(next)
      queue.push(next)
    }
  }
  return false
}
