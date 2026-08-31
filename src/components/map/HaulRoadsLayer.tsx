import { useEffect } from "react"
import type { FeatureCollection, LineString } from "geojson"
import type {
  DataDrivenPropertyValueSpecification,
  GeoJSONSource,
  Map as MapLibreMap,
  MapLayerMouseEvent,
} from "maplibre-gl"

import { useMineMap } from "@/components/map/MineMapContext"
import { MAP_LAYER, MAP_SOURCE } from "@/features/map/map.types"
import type { RoadFeatureProps } from "@/features/map/map.types"
import { ROAD_CLASS_PAINT } from "@/lib/map/roadStyle"

const OPEN = ROAD_CLASS_PAINT.main
const RESTRICTED = ROAD_CLASS_PAINT.restricted
const CLOSED = ROAD_CLASS_PAINT.closed
const UNKNOWN = ROAD_CLASS_PAINT.unknown

const COLOR_EXPR = [
  "match",
  ["get", "roadClass"],
  "restricted",
  RESTRICTED.color,
  "closed",
  CLOSED.color,
  "unknown",
  UNKNOWN.color,
  OPEN.color,
] as DataDrivenPropertyValueSpecification<string>

const CASING_COLOR_EXPR = [
  "case",
  ["==", ["get", "selected"], 1],
  "#F8FAFC",
  [
    "match",
    ["get", "roadClass"],
    "restricted",
    RESTRICTED.casing,
    "closed",
    CLOSED.casing,
    "unknown",
    UNKNOWN.casing,
    OPEN.casing,
  ],
] as DataDrivenPropertyValueSpecification<string>

function ensureRoadsLayers(map: MapLibreMap) {
  if (!map.getSource(MAP_SOURCE.roads)) {
    map.addSource(MAP_SOURCE.roads, {
      type: "geojson",
      data: { type: "FeatureCollection", features: [] },
    })
  }
  if (!map.getLayer(MAP_LAYER.roadsCasing)) {
    map.addLayer({
      id: MAP_LAYER.roadsCasing,
      type: "line",
      source: MAP_SOURCE.roads,
      layout: {
        "line-cap": "round",
        "line-join": "round",
      },
      paint: {
        "line-color": CASING_COLOR_EXPR,
        "line-width": ["case", ["==", ["get", "selected"], 1], 8, 5.4],
        "line-opacity": 0.9,
      },
    })
  }
  if (!map.getLayer(MAP_LAYER.roads)) {
    map.addLayer({
      id: MAP_LAYER.roads,
      type: "line",
      source: MAP_SOURCE.roads,
      layout: {
        "line-cap": "round",
        "line-join": "round",
      },
      paint: {
        "line-color": COLOR_EXPR,
        "line-width": [
          "case",
          ["==", ["get", "selected"], 1],
          5.2,
          ["match", ["get", "roadClass"], "closed", CLOSED.width, "restricted", RESTRICTED.width, "unknown", UNKNOWN.width, OPEN.width],
        ],
        "line-opacity": ["match", ["get", "roadClass"], "unknown", 0.85, 0.96],
        "line-dasharray": [
          "case",
          ["==", ["get", "roadClass"], "closed"],
          ["literal", CLOSED.dash ?? [2.2, 2]],
          ["==", ["get", "roadClass"], "restricted"],
          ["literal", RESTRICTED.dash ?? [4, 2]],
          ["==", ["get", "roadClass"], "unknown"],
          ["literal", UNKNOWN.dash ?? [1.4, 2.2]],
          ["literal", [1, 0]],
        ],
      },
    })
  }
}

const ROAD_LAYER_IDS = [MAP_LAYER.roads, MAP_LAYER.roadsCasing] as const

export function HaulRoadsLayer({
  data,
  visible,
  interactive,
  onRoadClick,
}: {
  data: FeatureCollection<LineString, RoadFeatureProps>
  visible: boolean
  interactive?: boolean
  onRoadClick?: (id: string) => void
}) {
  const { map, ready } = useMineMap()

  useEffect(() => {
    if (!map || !ready) return
    ensureRoadsLayers(map)
    const src = map.getSource(MAP_SOURCE.roads) as GeoJSONSource | undefined
    src?.setData(data)
    const visibility = visible ? "visible" : "none"
    for (const id of ROAD_LAYER_IDS) {
      if (map.getLayer(id)) {
        map.setLayoutProperty(id, "visibility", visibility)
      }
    }
  }, [map, ready, data, visible])

  useEffect(() => {
    if (!map || !ready || !interactive || !visible) return
    const onClick = (e: MapLayerMouseEvent) => {
      const id = e.features?.[0]?.properties?.id as string | undefined
      if (id) onRoadClick?.(id)
    }
    const enter = () => {
      map.getCanvas().style.cursor = "pointer"
    }
    const leave = () => {
      map.getCanvas().style.cursor = ""
    }
    for (const id of ROAD_LAYER_IDS) {
      map.on("click", id, onClick)
      map.on("mouseenter", id, enter)
      map.on("mouseleave", id, leave)
    }
    return () => {
      for (const id of ROAD_LAYER_IDS) {
        map.off("click", id, onClick)
        map.off("mouseenter", id, enter)
        map.off("mouseleave", id, leave)
      }
    }
  }, [map, ready, interactive, visible, onRoadClick])

  return null
}
