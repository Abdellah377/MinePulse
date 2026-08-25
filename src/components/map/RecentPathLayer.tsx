import { useEffect } from "react"
import type { FeatureCollection, LineString } from "geojson"
import type { GeoJSONSource, Map as MapLibreMap } from "maplibre-gl"

import { useMineMap } from "@/components/map/MineMapContext"
import { MAP_LAYER, MAP_SOURCE } from "@/features/map/map.types"

function ensureRecentPath(map: MapLibreMap) {
  if (map.getSource(MAP_SOURCE.recentPath)) return
  map.addSource(MAP_SOURCE.recentPath, {
    type: "geojson",
    data: { type: "FeatureCollection", features: [] },
  })
  map.addLayer({
    id: MAP_LAYER.recentPath,
    type: "line",
    source: MAP_SOURCE.recentPath,
    layout: {
      "line-cap": "round",
      "line-join": "round",
    },
    paint: {
      "line-color": "#3d8c14",
      "line-width": 3,
      "line-opacity": 0.85,
    },
  })
  map.addLayer({
    id: MAP_LAYER.recentPathArrow,
    type: "symbol",
    source: MAP_SOURCE.recentPath,
    layout: {
      "symbol-placement": "line",
      "symbol-spacing": 40,
      "text-field": "▶",
      "text-size": 12,
      "text-allow-overlap": true,
    },
    paint: {
      "text-color": "#3d8c14",
      "text-halo-color": "#ffffff",
      "text-halo-width": 1,
    },
  })
}

export function RecentPathLayer({
  data,
  visible,
}: {
  data: FeatureCollection<LineString>
  visible: boolean
}) {
  const { map, ready } = useMineMap()

  useEffect(() => {
    if (!map || !ready) return
    ensureRecentPath(map)
    const src = map.getSource(MAP_SOURCE.recentPath) as GeoJSONSource | undefined
    src?.setData(data)
    for (const id of [MAP_LAYER.recentPath, MAP_LAYER.recentPathArrow]) {
      if (map.getLayer(id)) {
        map.setLayoutProperty(id, "visibility", visible ? "visible" : "none")
      }
    }
  }, [map, ready, data, visible])

  return null
}
