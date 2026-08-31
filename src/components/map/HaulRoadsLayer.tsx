import { useEffect } from "react"
import type { FeatureCollection, LineString } from "geojson"
import type { GeoJSONSource, Map as MapLibreMap, MapLayerMouseEvent } from "maplibre-gl"

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
        "restricted",
        "#c4a062",
        "closed",
        "#6b7280",
        "#a89070",
      ],
      "line-width": [
        "case",
        ["==", ["get", "selected"], 1],
        5,
        ["match", ["get", "roadClass"], "closed", 2.4, "restricted", 2.8, 3.2],
      ],
      "line-opacity": ["match", ["get", "roadClass"], "closed", 0.55, 0.8],
      "line-dasharray": [
        "case",
        ["==", ["get", "roadClass"], "closed"],
        ["literal", [2, 2]],
        ["==", ["get", "roadClass"], "restricted"],
        ["literal", [4, 2]],
        ["literal", [1, 0]],
      ],
    },
  })
}

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
    if (map.getLayer(MAP_LAYER.roads)) {
      map.setLayoutProperty(MAP_LAYER.roads, "visibility", visible ? "visible" : "none")
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
    map.on("click", MAP_LAYER.roads, onClick)
    map.on("mouseenter", MAP_LAYER.roads, enter)
    map.on("mouseleave", MAP_LAYER.roads, leave)
    return () => {
      map.off("click", MAP_LAYER.roads, onClick)
      map.off("mouseenter", MAP_LAYER.roads, enter)
      map.off("mouseleave", MAP_LAYER.roads, leave)
    }
  }, [map, ready, interactive, visible, onRoadClick])

  return null
}
