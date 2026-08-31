import type { Equipment, Vec2 } from "@/lib/mock/types"
import { workspaceToLngLat } from "@/features/map/map.utils"

export const EQUIPMENT_FOCUS_ZOOM = 15.5

export function mapCameraForEquipment(
  equipment: Pick<Equipment, "position"> | null | undefined,
): { center: [number, number]; zoom: number } | null {
  const position = equipment?.position
  if (!hasMappablePosition(position)) return null
  const center = workspaceToLngLat(position)
  if (!Number.isFinite(center[0]) || !Number.isFinite(center[1])) return null
  return { center, zoom: EQUIPMENT_FOCUS_ZOOM }
}

export function mapFocusEpoch(
  equipmentId: string | null | undefined,
  hasPosition: boolean,
  requestId?: number | string | null,
): string | null {
  if (!equipmentId || !hasPosition) return null
  return `${equipmentId}:${requestId ?? "open"}`
}

export function hasMappablePosition(position: Vec2 | null | undefined): position is Vec2 {
  return position != null && Number.isFinite(position.x) && Number.isFinite(position.y)
}
