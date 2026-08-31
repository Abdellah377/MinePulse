import type { EquipmentState, EquipmentType, ZoneType } from "@/lib/mock/types"

export type MapTool = "select" | "polygon" | "polyline" | "vertex" | "delete"

export type BasemapId = "hybrid" | "dataviz"

export type RoadClass = "main" | "secondary" | "restricted" | "closed" | "unknown"

export interface SiteGeoConfig {
  id: string
  name: string
  center: [number, number]
  zoom: number
  minZoom: number
  maxZoom: number
  bearing: number
  pitch: number
  bounds: { west: number; south: number; east: number; north: number }
  workspace: { minX: number; minY: number; maxX: number; maxY: number }
}

export interface EquipmentFeatureProps {
  id: string
  code: string
  type: EquipmentType
  state: EquipmentState
  stateColor: string
  zoneId: string | null
  zoneName: string
  heading: number | null
  speedKmh: number | null
  timeInStateMin: number | null
  selected: boolean
}

export interface ZoneFeatureProps {
  id: string
  name: string
  type: ZoneType
  color: string
  description: string
  capacity: number | null
  count: number
  active: boolean
  /** 1 = selected, 0 = not (MapLibre-friendly) */
  selected: number | boolean
  /** 1 = congested, 0 = not (MapLibre-friendly) */
  congested: number | boolean
}

export interface RoadFeatureProps {
  id: string
  name: string
  roadClass: RoadClass
  status: string
  fromZoneId: string
  toZoneId: string
  distanceKm: number | null
  selected: number
}

export const MAP_SOURCE = {
  equipment: "mp-equipment",
  zones: "mp-zones",
  roads: "mp-roads",
  recentPath: "mp-recent-path",
  draft: "mp-draft",
  vertices: "mp-vertices",
} as const

export const MAP_LAYER = {
  roadsCasing: "mp-roads-casing",
  roads: "mp-roads-line",
  zonesFill: "mp-zones-fill",
  zonesLine: "mp-zones-line",
  zonesLabel: "mp-zones-label",
  equipmentHaloOuter: "mp-equipment-halo-outer",
  equipmentHalo: "mp-equipment-halo",
  equipment: "mp-equipment-symbol",
  equipmentLabel: "mp-equipment-label",
  recentPath: "mp-recent-path-line",
  recentPathArrow: "mp-recent-path-arrow",
  draftLine: "mp-draft-line",
  draftPoints: "mp-draft-points",
  vertices: "mp-vertices",
} as const
