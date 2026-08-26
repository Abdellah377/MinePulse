import { useEffect, useRef } from "react"

import {
  LIVE_MOVEMENT_INTERVAL_MS,
  SIMULATE_LIVE_MOVEMENT,
} from "@/features/map/map.constants"
import { SPOTLIGHT, SPOTLIGHT_CODES } from "@/lib/mock/scenario"
import type { Equipment, RoutePath, Vec2 } from "@/lib/mock/types"
import { useOpsStore } from "@/lib/store/useOpsStore"
import { useApiMode } from "@/lib/api/client"

function lerp(a: Vec2, b: Vec2, t: number): Vec2 {
  return { x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t }
}

function progressAlong(points: Vec2[], t: number): Vec2 {
  if (points.length === 0) return { x: 0, y: 0 }
  if (points.length === 1) return points[0]
  const clamped = ((t % 1) + 1) % 1
  const segCount = points.length - 1
  const f = clamped * segCount
  const i = Math.min(segCount - 1, Math.floor(f))
  const local = f - i
  return lerp(points[i], points[i + 1], local)
}

export function advanceSimulatedPositions(
  equipment: Equipment[],
  routes: RoutePath[],
  bancBId: string | null,
  tick: number
): Equipment[] {
  if (useApiMode || !SIMULATE_LIVE_MOVEMENT) return equipment

  return equipment.map((eq) => {
    if (SPOTLIGHT_CODES.has(eq.code)) return eq
    if (bancBId && eq.zoneId === bancBId && eq.type === "haul_truck") return eq
    if (eq.state !== "mouvement_charge" && eq.state !== "mouvement_vide") return eq

    const route =
      routes.find(
        (r) =>
          (eq.zoneId && r.fromZoneId === eq.zoneId) ||
          (eq.destinationZoneId && r.toZoneId === eq.destinationZoneId)
      ) ?? routes[0]
    if (!route || route.points.length < 2) return eq

    const seed =
      eq.id.split("").reduce((h, c) => (h * 31 + c.charCodeAt(0)) >>> 0, 0) / 0xffffffff
    const speed = 0.012 + seed * 0.018
    const t = (seed + tick * speed * (eq.state === "mouvement_charge" ? 1 : 0.85)) % 1
    const pos = progressAlong(route.points, t)
    const next = progressAlong(route.points, (t + 0.002) % 1)
    const heading = (Math.atan2(next.y - pos.y, next.x - pos.x) * 180) / Math.PI

    return {
      ...eq,
      position: pos,
      heading,
      speedKmh: 16 + seed * 14,
      lastUpdate: Date.now(),
    }
  })
}

export function buildRecentTrail(
  equipment: Equipment,
  routes: RoutePath[],
  samples = 12
): Vec2[] {
  if (useApiMode) return []
  const route =
    routes.find(
      (r) =>
        r.fromZoneId === equipment.zoneId ||
        r.toZoneId === equipment.destinationZoneId ||
        r.toZoneId === equipment.zoneId
    ) ?? null
  if (!route || route.points.length < 2 || !equipment.position) {
    const h = ((equipment.heading ?? 0) * Math.PI) / 180
    const pos = equipment.position ?? { x: 0, y: 0 }
    return Array.from({ length: samples }, (_, i) => {
      const d = (samples - i) * 8
      return {
        x: pos.x - Math.cos(h) * d,
        y: pos.y - Math.sin(h) * d,
      }
    })
  }
  return route.points
}

/** Controlled map simulation — updates GeoJSON via store; preserves camera/selection. */
export function useMapLiveSimulation(enabled: boolean) {
  const setEquipment = useOpsStore((s) => s.setEquipment)
  const routes = useOpsStore((s) => s.routes)
  const zones = useOpsStore((s) => s.zones)
  const selectedSiteId = useOpsStore((s) => s.selectedSiteId)
  const tickRef = useRef(0)

  useEffect(() => {
    if (useApiMode || !enabled || !SIMULATE_LIVE_MOVEMENT) return
    const id = window.setInterval(() => {
      tickRef.current += 1
      const bancB = zones.find(
        (z) => z.siteId === selectedSiteId && z.name === SPOTLIGHT.bancBName
      )
      const siteRoutes = routes.filter((r) => r.siteId === selectedSiteId)
      setEquipment((eqs) =>
        advanceSimulatedPositions(eqs, siteRoutes, bancB?.id ?? null, tickRef.current)
      )
    }, LIVE_MOVEMENT_INTERVAL_MS)
    return () => window.clearInterval(id)
  }, [enabled, setEquipment, routes, zones, selectedSiteId])
}
