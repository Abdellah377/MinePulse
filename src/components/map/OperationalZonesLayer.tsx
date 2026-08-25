import { useEffect } from "react"
import type { FeatureCollection, Polygon } from "geojson"
import type { GeoJSONSource, Map as MapLibreMap, MapLayerMouseEvent } from "maplibre-gl"

import { useMineMap } from "@/components/map/MineMapContext"
import { MAP_LAYER, MAP_SOURCE } from "@/features/map/map.types"
import type { ZoneFeatureProps } from "@/features/map/map.types"

function ensureZoneLayers(map: MapLibreMap) {
  if (map.getSource(MAP_SOURCE.zones)) return
  map.addSource(MAP_SOURCE.zones, {
    type: "geojson",
    data: { type: "FeatureCollection", features: [] },
  })
  map.addLayer({
    id: MAP_LAYER.zonesFill,
    type: "fill",
    source: MAP_SOURCE.zones,
    paint: {
      "fill-color": ["coalesce", ["get", "color"], "#2F6FED"],
      "fill-opacity": [
        "case",
        ["==", ["get", "selected"], 1],
        0.48,
        ["==", ["get", "congested"], 1],
        0.4,
        0.3,
      ],
    },
  })
  map.addLayer({
    id: MAP_LAYER.zonesLine,
    type: "line",
    source: MAP_SOURCE.zones,
    paint: {
      "line-color": [
        "case",
        ["==", ["get", "congested"], 1],
        "#d82010",
        ["==", ["get", "selected"], 1],
        "#3d8c14",
        ["coalesce", ["get", "color"], "#2F6FED"],
      ],
      "line-width": [
        "case",
        ["==", ["get", "selected"], 1],
        3,
        ["==", ["get", "congested"], 1],
        2.5,
        2,
      ],
      "line-opacity": 1,
    },
  })
  map.addLayer({
    id: MAP_LAYER.zonesLabel,
    type: "symbol",
    source: MAP_SOURCE.zones,
    layout: {
      "text-field": [
        "case",
        ["==", ["get", "congested"], 1],
        ["concat", ["upcase", ["get", "name"]], " · ", ["to-string", ["get", "count"]], "/", ["to-string", ["get", "capacity"]]],
        ["upcase", ["get", "name"]],
      ],
      "text-size": 12,
      "text-font": ["Noto Sans Bold", "Noto Sans Regular"],
      "text-max-width": 10,
      "text-allow-overlap": true,
      "text-ignore-placement": false,
      "symbol-sort-key": ["case", ["==", ["get", "congested"], 1], 0, 1],
    },
    paint: {
      "text-color": ["case", ["==", ["get", "congested"], 1], "#ffffff", "#1c1d21"],
      "text-halo-color": ["case", ["==", ["get", "congested"], 1], "#d82010", "#ffffff"],
      "text-halo-width": 1.75,
    },
  })
}

export function OperationalZonesLayer({
  data,
  visible,
  interactive,
  onZoneClick,
}: {
  data: FeatureCollection<Polygon, ZoneFeatureProps>
  visible: boolean
  interactive?: boolean
  onZoneClick?: (id: string) => void
}) {
  const { map, ready } = useMineMap()

  useEffect(() => {
    if (!map || !ready) return
    ensureZoneLayers(map)
    const src = map.getSource(MAP_SOURCE.zones) as GeoJSONSource | undefined
    src?.setData(data)
    for (const id of [MAP_LAYER.zonesFill, MAP_LAYER.zonesLine, MAP_LAYER.zonesLabel]) {
      if (map.getLayer(id)) {
        map.setLayoutProperty(id, "visibility", visible ? "visible" : "none")
      }
    }
  }, [map, ready, data, visible])

  useEffect(() => {
    if (!map || !ready || !interactive) return
    const onClick = (e: MapLayerMouseEvent) => {
      const f = e.features?.[0]
      const id = f?.properties?.id as string | undefined
      if (id) onZoneClick?.(id)
    }
    const enter = () => {
      map.getCanvas().style.cursor = "pointer"
    }
    const leave = () => {
      map.getCanvas().style.cursor = ""
    }
    map.on("click", MAP_LAYER.zonesFill, onClick)
    map.on("mouseenter", MAP_LAYER.zonesFill, enter)
    map.on("mouseleave", MAP_LAYER.zonesFill, leave)
    return () => {
      map.off("click", MAP_LAYER.zonesFill, onClick)
      map.off("mouseenter", MAP_LAYER.zonesFill, enter)
      map.off("mouseleave", MAP_LAYER.zonesFill, leave)
    }
  }, [map, ready, interactive, onZoneClick])

  return null
}
