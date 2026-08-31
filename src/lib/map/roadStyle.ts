import type { RoadClass } from "@/features/map/map.types"
import type { RoadOperationalStatus } from "@/lib/map/roadNetwork"

export const ROAD_STATUS_PAINT: Record<
  RoadOperationalStatus,
  { color: string; casing: string; dash: number[] | null; width: number }
> = {
  OPEN: { color: "#7CFFF0", casing: "#082028", dash: null, width: 3.4 },
  RESTRICTED: { color: "#F5A524", casing: "#2A1A08", dash: [4, 2], width: 3.2 },
  CLOSED: { color: "#F25C54", casing: "#2A0C0C", dash: [2.2, 2], width: 3.0 },
  UNKNOWN: { color: "#94A3B8", casing: "#1E293B", dash: [1.4, 2.2], width: 2.6 },
}

export const ROAD_CLASS_PAINT: Record<RoadClass, (typeof ROAD_STATUS_PAINT)[RoadOperationalStatus]> = {
  main: ROAD_STATUS_PAINT.OPEN,
  secondary: ROAD_STATUS_PAINT.OPEN,
  restricted: ROAD_STATUS_PAINT.RESTRICTED,
  closed: ROAD_STATUS_PAINT.CLOSED,
  unknown: ROAD_STATUS_PAINT.UNKNOWN,
}

export const ROAD_DRAFT_COLOR = ROAD_STATUS_PAINT.OPEN.color
