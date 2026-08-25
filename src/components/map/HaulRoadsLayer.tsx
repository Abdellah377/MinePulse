import { useEffect } from "react"
import type { FeatureCollection, LineString } from "geojson"
import type { GeoJSONSource, Map as MapLibreMap } from "maplibre-gl"

import { useMineMap } from "@/components/map/MineMapContext"
import { MAP_LAYER, MAP_SOURCE } from "@/features/map/map.types"
import type { RoadFeatureProps } from "@/features/map/map.types"

function ensureRoadsLayers(map: MapLibreMap) {
  if (map.getSource(MAP_SOURCE.roads)) return
  map.addSource(MAP_SOURCE.roads, {
    type: "geojson",
    data: { type: "FeatureCollection", features: [] },
  })
  map.addLayer({
    id: MAP_LAYER.roads,
    type: "line",
    source: MAP_SOURCE.roads,
    layout: {
      "line-cap": "round",
      "line-join": "round",
    },
    paint: {
      "line-color": [
        "match",
        ["get", "roadClass"],
        "main",
        "#c4a574",
        "restricted",
        "#d82010",
        "closed",
        "#6b7280",
        "#a89070",
      ],
      "line-width": ["match", ["get", "roadClass"], "main", 3.5, "restricted", 2.5, 2.2],
      "line-opacity": 0.75,
    },
  })
}

export function HaulRoadsLayer({
  data,
  visible,
}: {
  data: FeatureCollection<LineString, RoadFeatureProps>
  visible: boolean
}) {
  const { map, ready } = useMineMap()

  useEffect(() => {
    if (!map || !ready) return
    ensureRoadsLayers(map)
    const src = map.getSource(MAP_SOURCE.roads) as GeoJSONSource | undefined
    src?.setData(data)
    if (map.getLayer(MAP_LAYER.roads)) {
      map.setLayoutProperty(MAP_LAYER.roads, "visibility", visible ? "visible" : "none")
    }
  }, [map, ready, data, visible])

  return null
}
