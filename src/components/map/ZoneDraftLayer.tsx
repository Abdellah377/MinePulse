import { useEffect, useRef } from "react"
import type { FeatureCollection } from "geojson"
import type { GeoJSONSource, Map as MapLibreMap, MapMouseEvent } from "maplibre-gl"

import { useMineMap } from "@/components/map/MineMapContext"
import { MAP_LAYER, MAP_SOURCE } from "@/features/map/map.types"

function ensureDraftLayers(map: MapLibreMap, color: string) {
  if (!map.getSource(MAP_SOURCE.draft)) {
    map.addSource(MAP_SOURCE.draft, {
      type: "geojson",
      data: { type: "FeatureCollection", features: [] },
    })
    map.addLayer({
      id: MAP_LAYER.draftLine,
      type: "line",
      source: MAP_SOURCE.draft,
      filter: ["==", ["geometry-type"], "LineString"],
      paint: {
        "line-color": color,
        "line-width": 3,
        "line-dasharray": [2, 1],
      },
    })
    map.addLayer({
      id: "mp-draft-fill",
      type: "fill",
      source: MAP_SOURCE.draft,
      filter: ["==", ["geometry-type"], "Polygon"],
      paint: {
        "fill-color": color,
        "fill-opacity": 0.3,
      },
    })
    map.addLayer({
      id: MAP_LAYER.draftPoints,
      type: "circle",
      source: MAP_SOURCE.draft,
      filter: ["==", ["geometry-type"], "Point"],
      paint: {
        "circle-radius": 7,
        "circle-color": "#ffffff",
        "circle-stroke-width": 3,
        "circle-stroke-color": color,
      },
    })
  } else {
    map.setPaintProperty(MAP_LAYER.draftLine, "line-color", color)
    map.setPaintProperty("mp-draft-fill", "fill-color", color)
    map.setPaintProperty(MAP_LAYER.draftPoints, "circle-stroke-color", color)
  }
}

export function ZoneDraftLayer({
  data,
  enabled,
  color = "#2F6FED",
  onMapClick,
  onDoubleClickFinish,
  pointCount = 0,
}: {
  data: FeatureCollection
  enabled: boolean
  color?: string
  onMapClick?: (lngLat: [number, number]) => void
  onDoubleClickFinish?: () => void
  pointCount?: number
}) {
  const { map, ready } = useMineMap()
  const pointCountRef = useRef(pointCount)
  pointCountRef.current = pointCount

  useEffect(() => {
    if (!map || !ready) return
    ensureDraftLayers(map, color)
    const src = map.getSource(MAP_SOURCE.draft) as GeoJSONSource | undefined
    src?.setData(data)
  }, [map, ready, data, color])

  useEffect(() => {
    if (!map || !ready || !enabled || !onMapClick) return

    const handler = (e: MapMouseEvent) => {
      onMapClick([e.lngLat.lng, e.lngLat.lat])
    }
    const dblHandler = (e: MapMouseEvent) => {
      e.preventDefault()
      if (pointCountRef.current >= 3) onDoubleClickFinish?.()
    }

    // Pan/zoom locking is handled exclusively by <MapInteractionLock> in Carte.tsx
    // to avoid two effects fighting over map.dragPan/doubleClickZoom state.
    map.on("click", handler)
    map.on("dblclick", dblHandler)

    return () => {
      map.off("click", handler)
      map.off("dblclick", dblHandler)
    }
  }, [map, ready, enabled, onMapClick, onDoubleClickFinish])

  return null
}
