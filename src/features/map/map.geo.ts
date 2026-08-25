import booleanPointInPolygon from "@turf/boolean-point-in-polygon"
import { point, polygon } from "@turf/helpers"

import type { Equipment, Zone, ZoneType } from "@/lib/mock/types"
import { workspaceToLngLat } from "@/features/map/map.utils"

const PROBABLE_ACTIVITY: Partial<Record<ZoneType, string>> = {
  fuel: "ravitaillement",
  atelier: "maintenance / atelier",
  chargement: "chargement ou attente de chargement",
  dechargement: "déchargement",
  concasseur: "déchargement concasseur",
  parking: "stationnement / fin de cycle",
  restreinte: "présence en zone restreinte",
}

export interface ZoneMembership {
  zone: Zone
  probableActivity: string
  inference: string
}

/**
 * Client-side point-in-polygon. Exposed as contextual inference — not a confirmed cause.
 */
export function findContainingZones(equipment: Equipment, zones: Zone[]): Zone[] {
  if (!equipment.position) return []
  const [lng, lat] = workspaceToLngLat(equipment.position)
  const pt = point([lng, lat])
  return zones.filter((z) => {
    if (z.points.length < 3) return false
    const ring = z.points.map((p) => workspaceToLngLat(p))
    const first = ring[0]
    const last = ring[ring.length - 1]
    const closed =
      first[0] === last[0] && first[1] === last[1] ? ring : [...ring, first]
    try {
      return booleanPointInPolygon(pt, polygon([closed]))
    } catch {
      return false
    }
  })
}

export function inferEquipmentContext(
  equipment: Equipment,
  zones: Zone[]
): ZoneMembership | null {
  const containing = findContainingZones(equipment, zones)
  const zone =
    containing.find((z) => z.id === equipment.zoneId) ?? containing[0] ?? null
  if (!zone) return null
  const activity = PROBABLE_ACTIVITY[zone.type] ?? "activité opérationnelle"
  return {
    zone,
    probableActivity: activity,
    inference: `${equipment.code} est positionné dans la zone « ${zone.name} ». Activité probable : ${activity}. À confirmer.`,
  }
}

export function avgWaitInZone(equipment: Equipment[], zoneId: string): number {
  const inside = equipment.filter((e) => e.zoneId === zoneId)
  if (inside.length === 0) return 0
  return (
    inside.reduce((sum, e) => sum + e.waitingMinutesThisShift / Math.max(1, e.tripsThisShift || 1), 0) /
    inside.length
  )
}

export function zoneConditionLabel(count: number, capacity: number): string {
  if (capacity <= 0) return "ouverte"
  const ratio = count / capacity
  if (ratio > 1) return "congestion"
  if (ratio >= 0.7) return "tendue"
  if (ratio >= 0.4) return "normale"
  return "sous-utilisée"
}
