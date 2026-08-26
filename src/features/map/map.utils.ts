import type { Feature, FeatureCollection, LineString, Point, Polygon, Position } from "geojson"

import type { Equipment, RoutePath, Vec2, Zone } from "@/lib/mock/types"
import { useApiMode } from "@/lib/api/client"
import { EQUIPMENT_STATE_LABEL, EQUIPMENT_TYPE_LABEL } from "@/lib/mock/types"
import { SITE_GEO, STATE_HEX } from "@/features/map/map.constants"
import type {
  EquipmentFeatureProps,
  RoadClass,
  RoadFeatureProps,
  SiteGeoConfig,
  ZoneFeatureProps,
} from "@/features/map/map.types"

export function workspaceToLngLat(
  point: Vec2,
  site: SiteGeoConfig = SITE_GEO
): [number, number] {
  const { workspace: w, bounds: b } = site
  const nx = (point.x - w.minX) / (w.maxX - w.minX)
  const ny = (point.y - w.minY) / (w.maxY - w.minY)
  const lng = b.west + nx * (b.east - b.west)
  // SVG y grows downward; geographic lat grows northward
  const lat = b.north - ny * (b.north - b.south)
  return [lng, lat]
}

export function lngLatToWorkspace(
  lngLat: [number, number],
  site: SiteGeoConfig = SITE_GEO
): Vec2 {
  const { workspace: w, bounds: b } = site
  const [lng, lat] = lngLat
  const nx = (lng - b.west) / (b.east - b.west)
  const ny = (b.north - lat) / (b.north - b.south)
  return {
    x: w.minX + nx * (w.maxX - w.minX),
    y: w.minY + ny * (w.maxY - w.minY),
  }
}

function closeRing(coords: Position[]): Position[] {
  if (coords.length === 0) return coords
  const [fx, fy] = coords[0]
  const [lx, ly] = coords[coords.length - 1]
  if (fx === lx && fy === ly) return coords
  return [...coords, [fx, fy]]
}

export function equipmentToGeoJSON(
  equipment: Equipment[],
  zones: Zone[],
  selectedId: string | null = null,
  nowMs?: number
): FeatureCollection<Point, EquipmentFeatureProps> {
  const zoneById = new Map(zones.map((z) => [z.id, z]))
  const now =
    nowMs ??
    (equipment.length
      ? Math.max(...equipment.map((e) => e.lastUpdate || 0), 0) || Date.now() // wall fallback if no lastUpdate
      : Date.now()) // empty fleet
  return {
    type: "FeatureCollection",
    features: equipment
      .filter((eq) => eq.position != null)
      .map((eq) => {
      const zone = eq.zoneId ? zoneById.get(eq.zoneId) : undefined
      const timeInStateMin = useApiMode ? null : Math.max(1, Math.round((now - (eq.lastUpdate ?? now)) / 60_000))
      return {
        type: "Feature",
        id: eq.id,
        geometry: {
          type: "Point",
          coordinates: workspaceToLngLat(eq.position!),
        },
        properties: {
          id: eq.id,
          code: eq.code,
          type: eq.type,
          state: eq.state,
          stateColor: STATE_HEX[eq.state],
          zoneId: eq.zoneId,
          zoneName: zone?.name ?? "—",
          heading: eq.heading,
          speedKmh: eq.speedKmh,
          timeInStateMin,
          selected: eq.id === selectedId,
        },
      }
    }),
  }
}

export function zonesToGeoJSON(
  zones: Zone[],
  equipment: Equipment[],
  selectedId: string | null = null
): FeatureCollection<Polygon, ZoneFeatureProps> {
  return {
    type: "FeatureCollection",
    features: zones
      .filter((z) => {
        const hasGeo = Array.isArray(z.ringLngLat) && z.ringLngLat.length >= 3
        const hasWs = Array.isArray(z.points) && z.points.length >= 3
        return hasGeo || hasWs
      })
      .map((z) => {
        const count = equipment.filter((e) => e.zoneId === z.id).length
        const congested = !useApiMode && z.capacity != null && z.capacity > 0 && count > z.capacity
        const ring =
          z.ringLngLat && z.ringLngLat.length >= 3
            ? closeRing(z.ringLngLat.map(([lng, lat]) => [lng, lat]))
            : closeRing(z.points.map((p) => workspaceToLngLat(p)))
        return {
          type: "Feature",
          id: z.id,
          geometry: {
            type: "Polygon",
            coordinates: [ring],
          },
          properties: {
            id: z.id,
            name: z.name,
            type: z.type,
            color: z.color,
            description: z.description,
            capacity: z.capacity,
            count,
            active: true,
            selected: z.id === selectedId ? 1 : 0,
            congested: congested ? 1 : 0,
          },
        }
      }),
  }
}

function classifyRoad(route: RoutePath, zones: Zone[]): RoadClass {
  // Neutral cartographic style, not a claim that a road is open/restricted.
  if (useApiMode) return "secondary"
  const from = zones.find((z) => z.id === route.fromZoneId)
  const to = zones.find((z) => z.id === route.toZoneId)
  if (from?.type === "restreinte" || to?.type === "restreinte") return "restricted"
  if (
    (from?.type === "chargement" || from?.type === "dechargement" || from?.type === "concasseur") &&
    (to?.type === "chargement" || to?.type === "dechargement" || to?.type === "concasseur")
  ) {
    return "main"
  }
  return "secondary"
}

export function routesToGeoJSON(
  routes: RoutePath[],
  zones: Zone[]
): FeatureCollection<LineString, RoadFeatureProps> {
  return {
    type: "FeatureCollection",
    features: routes.map((r) => ({
      type: "Feature",
      id: r.id,
      geometry: {
        type: "LineString",
        coordinates: r.points.map((p) => workspaceToLngLat(p)),
      },
      properties: {
        id: r.id,
        roadClass: classifyRoad(r, zones),
        fromZoneId: r.fromZoneId,
        toZoneId: r.toZoneId,
        distanceKm: r.distanceKm,
      },
    })),
  }
}

export function draftLngLatToGeoJSON(lngLatPoints: [number, number][]): FeatureCollection {
  if (lngLatPoints.length === 0) {
    return { type: "FeatureCollection", features: [] }
  }
  const coords = lngLatPoints.map(([lng, lat]) => [lng, lat] as [number, number])
  const features: Feature[] = [
    {
      type: "Feature",
      properties: {},
      geometry: { type: "LineString", coordinates: coords },
    },
    ...coords.map(
      (c): Feature => ({
        type: "Feature",
        properties: {},
        geometry: { type: "Point", coordinates: c },
      })
    ),
  ]
  if (lngLatPoints.length >= 3) {
    features.unshift({
      type: "Feature",
      properties: { closed: true },
      geometry: { type: "Polygon", coordinates: [closeRing(coords)] },
    })
  }
  return { type: "FeatureCollection", features }
}

export function draftPointsToGeoJSON(points: Vec2[]): FeatureCollection {
  if (points.length === 0) {
    return { type: "FeatureCollection", features: [] }
  }
  const coords = points.map((p) => workspaceToLngLat(p))
  const features: Feature[] = [
    {
      type: "Feature",
      properties: {},
      geometry: { type: "LineString", coordinates: coords },
    },
    ...coords.map(
      (c): Feature => ({
        type: "Feature",
        properties: {},
        geometry: { type: "Point", coordinates: c },
      })
    ),
  ]
  if (points.length >= 3) {
    features.unshift({
      type: "Feature",
      properties: { closed: true },
      geometry: { type: "Polygon", coordinates: [closeRing(coords)] },
    })
  }
  return { type: "FeatureCollection", features }
}

export function recentPathToGeoJSON(
  points: Vec2[]
): FeatureCollection<LineString> {
  if (points.length < 2) {
    return { type: "FeatureCollection", features: [] }
  }
  return {
    type: "FeatureCollection",
    features: [
      {
        type: "Feature",
        properties: {},
        geometry: {
          type: "LineString",
          coordinates: points.map((p) => workspaceToLngLat(p)),
        },
      },
    ],
  }
}

export function fitBoundsFromZone(zone: Zone): [[number, number], [number, number]] | null {
  const coords =
    zone.ringLngLat && zone.ringLngLat.length >= 2
      ? zone.ringLngLat
      : zone.points?.length >= 2
        ? zone.points.map((p) => workspaceToLngLat(p))
        : null
  if (!coords || coords.length < 2) return null
  let minLng = Infinity
  let minLat = Infinity
  let maxLng = -Infinity
  let maxLat = -Infinity
  for (const [lng, lat] of coords) {
    minLng = Math.min(minLng, lng)
    minLat = Math.min(minLat, lat)
    maxLng = Math.max(maxLng, lng)
    maxLat = Math.max(maxLat, lat)
  }
  const pad = 0.0008
  return [
    [minLng - pad, minLat - pad],
    [maxLng + pad, maxLat + pad],
  ]
}

export function fitBoundsFromEquipment(equipment: Equipment[]): [[number, number], [number, number]] | null {
  if (!equipment.some((e) => e.position != null)) return null
  let minLng = Infinity
  let minLat = Infinity
  let maxLng = -Infinity
  let maxLat = -Infinity
  for (const eq of equipment) {
    if (!eq.position) continue
    const [lng, lat] = workspaceToLngLat(eq.position)
    minLng = Math.min(minLng, lng)
    minLat = Math.min(minLat, lat)
    maxLng = Math.max(maxLng, lng)
    maxLat = Math.max(maxLat, lat)
  }
  const pad = 0.0015
  return [
    [minLng - pad, minLat - pad],
    [maxLng + pad, maxLat + pad],
  ]
}

export function equipmentPopupHtml(props: EquipmentFeatureProps): string {
  return `
    <div style="font:12px/1.35 'IBM Plex Sans',sans-serif;min-width:140px">
      <div style="font-weight:700;font-family:ui-monospace,monospace">${escapeHtml(props.code)}</div>
      <div style="color:#6b7280;margin-top:2px">${escapeHtml(EQUIPMENT_TYPE_LABEL[props.type])}</div>
      <div style="margin-top:6px"><span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${props.stateColor};margin-right:6px"></span>${escapeHtml(EQUIPMENT_STATE_LABEL[props.state])}</div>
      <div style="color:#6b7280;margin-top:4px">${escapeHtml(props.zoneName)} · ${props.timeInStateMin == null ? "Durée dans l’état indisponible" : `${props.timeInStateMin} min`}</div>
    </div>
  `
}

function escapeHtml(s: string): string {
  return s
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
}
