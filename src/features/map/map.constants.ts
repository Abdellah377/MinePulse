import siteConfig from "@/data/geo/site-khouribga.json"
import type { EquipmentState, EquipmentType } from "@/lib/mock/types"
import type { BasemapId, SiteGeoConfig } from "@/features/map/map.types"

export const SITE_GEO = siteConfig as SiteGeoConfig

/** Development flag — gradual motion along routes without teleportation. */
export const SIMULATE_LIVE_MOVEMENT = true

export const LIVE_MOVEMENT_INTERVAL_MS = 2_000

export const BASEMAP_STYLES: Record<BasemapId, { id: BasemapId; label: string; maptilerStyle: string }> = {
  hybrid: { id: "hybrid", label: "Satellite", maptilerStyle: "hybrid" },
  dataviz: { id: "dataviz", label: "Plan clair", maptilerStyle: "dataviz" },
}

export const DEFAULT_BASEMAP: BasemapId = "hybrid"

/** Hex colours matching Film palette (index.css) — usable in MapLibre paint. */
export const STATE_HEX: Record<EquipmentState, string> = {
  mouvement_charge: "#78a828",
  mouvement_vide: "#e8c800",
  attente_charge: "#e08a2e",
  attente_dechargement: "#e08a2e",
  chargement: "#3a7bd5",
  dechargement: "#3a7bd5",
  arret_exploitation: "#d82010",
  arret_materiel: "#d82010",
  arret_exterieur: "#d82010",
  arret_indetermine: "#d82010",
  eteint: "#5c6670",
  aucune_donnee: "#6b7280",
  indetermine: "#b0b6bf",
  ravitaillement: "#e08a2e",
  parking: "#7C8B84",
}

export const EQUIPMENT_ICON_IDS: Record<EquipmentType, string> = {
  haul_truck: "eq-haul_truck",
  excavator: "eq-excavator",
  loader: "eq-loader",
  dozer: "eq-dozer",
  drill: "eq-drill",
  grader: "eq-grader",
  water_truck: "eq-water_truck",
  light_vehicle: "eq-light_vehicle",
  other: "eq-other",
}

/** Map marker sizing — tuned for satellite basemap readability */
export const EQUIPMENT_MAP_STYLE = {
  iconSize: 0.82,
  iconSizeSelected: 1.02,
  haloRadius: 20,
  haloRadiusSelected: 26,
  haloOuterRadius: 32,
  haloOuterRadiusSelected: 40,
  labelSize: 13,
  labelSizeSelected: 14,
  labelOffset: [0, -2.35] as [number, number],
  labelMinZoom: 12,
} as const

export const ZONES_STORAGE_KEY = "minepulse.prototype.zones"

export function getMapTilerApiKey(): string {
  return (import.meta.env.VITE_MAPTILER_API_KEY as string | undefined)?.trim() ?? ""
}

export function hasMapTilerApiKey(): boolean {
  return getMapTilerApiKey().length > 0
}

/**
 * Provider-independent style URL builder.
 * Swap `maptilerStyle` / host later for OCP GIS, MBTiles, orthophotos, etc.
 */
export function buildBasemapStyleUrl(basemap: BasemapId = DEFAULT_BASEMAP): string | null {
  const key = getMapTilerApiKey()
  if (!key) return null
  const style = BASEMAP_STYLES[basemap]?.maptilerStyle ?? "hybrid"
  return `https://api.maptiler.com/maps/${style}/style.json?key=${encodeURIComponent(key)}`
}
