import type { Vec2 } from "@/lib/mock/types"
import { workspaceToLngLat } from "@/features/map/map.utils"

function haversineKm(lng1: number, lat1: number, lng2: number, lat2: number): number {
  const r = 6371
  const dLat = ((lat2 - lat1) * Math.PI) / 180
  const dLng = ((lng2 - lng1) * Math.PI) / 180
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos((lat1 * Math.PI) / 180) * Math.cos((lat2 * Math.PI) / 180) * Math.sin(dLng / 2) ** 2
  return 2 * r * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a))
}

/** Full-polyline distance. Never origin–destination shortcut. */
export function polylineDistanceKm(points: Vec2[]): number | null {
  if (points.length < 2) return null
  let total = 0
  for (let i = 1; i < points.length; i++) {
    const [lng1, lat1] = workspaceToLngLat(points[i - 1])
    const [lng2, lat2] = workspaceToLngLat(points[i])
    total += haversineKm(lng1, lat1, lng2, lat2)
  }
  return Math.round(total * 1000) / 1000
}

export function copyVertices(points: Vec2[]): Vec2[] {
  return points.map((p) => ({ x: p.x, y: p.y }))
}

/** Creating/editing returns the full vertex list; property-only saves leave geometry untouched. */
export function geometryToPersist(input: {
  isCreating: boolean
  draftPoints: Vec2[]
  roadEditingVertices: Vec2[] | null
}): Vec2[] | undefined {
  if (input.isCreating) {
    return input.draftPoints.length >= 2 ? copyVertices(input.draftPoints) : undefined
  }
  if (input.roadEditingVertices) {
    return input.roadEditingVertices.length >= 2 ? copyVertices(input.roadEditingVertices) : undefined
  }
  return undefined
}

export function canSaveRoadTrace(input: {
  isCreating: boolean
  draftPoints: Vec2[]
  roadEditingVertices: Vec2[] | null
}): boolean {
  if (input.isCreating) return input.draftPoints.length >= 2
  if (input.roadEditingVertices) return input.roadEditingVertices.length >= 2
  return true
}

function dist2(a: Vec2, b: Vec2) {
  const dx = a.x - b.x
  const dy = a.y - b.y
  return dx * dx + dy * dy
}

function projectOnSegment(p: Vec2, a: Vec2, b: Vec2): Vec2 {
  const dx = b.x - a.x
  const dy = b.y - a.y
  const len2 = dx * dx + dy * dy
  if (len2 === 0) return { x: a.x, y: a.y }
  const t = Math.max(0, Math.min(1, ((p.x - a.x) * dx + (p.y - a.y) * dy) / len2))
  return { x: a.x + t * dx, y: a.y + t * dy }
}

/** Insert a vertex on the closest segment. Requires at least 2 existing points. */
export function insertVertexOnPolyline(points: Vec2[], point: Vec2): Vec2[] {
  if (points.length < 2) return [...copyVertices(points), { x: point.x, y: point.y }]
  let bestIndex = 1
  let best = Number.POSITIVE_INFINITY
  for (let i = 0; i < points.length - 1; i++) {
    const projected = projectOnSegment(point, points[i], points[i + 1])
    const d = dist2(point, projected)
    if (d < best) {
      best = d
      bestIndex = i + 1
    }
  }
  const next = copyVertices(points)
  next.splice(bestIndex, 0, { x: point.x, y: point.y })
  return next
}

export function removeLastVertex(points: Vec2[]): Vec2[] {
  if (points.length <= 2) return copyVertices(points)
  return copyVertices(points.slice(0, -1))
}

/** Insert a midpoint on the longest segment so operators can densify a haul path. */
export function insertMidpointOnLongestSegment(points: Vec2[]): Vec2[] {
  if (points.length < 2) return copyVertices(points)
  let bestIndex = 0
  let best = -1
  for (let i = 0; i < points.length - 1; i++) {
    const d = dist2(points[i], points[i + 1])
    if (d > best) {
      best = d
      bestIndex = i
    }
  }
  const a = points[bestIndex]
  const b = points[bestIndex + 1]
  const next = copyVertices(points)
  next.splice(bestIndex + 1, 0, { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 })
  return next
}
