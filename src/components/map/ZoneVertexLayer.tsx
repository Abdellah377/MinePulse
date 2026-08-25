import { useEffect, useMemo, useRef } from "react"
import type { FeatureCollection, Point } from "geojson"
import type { GeoJSONSource, Map as MapLibreMap, MapLayerMouseEvent, MapMouseEvent } from "maplibre-gl"

import { useMineMap } from "@/components/map/MineMapContext"
import { MAP_LAYER, MAP_SOURCE } from "@/features/map/map.types"
import type { Vec2 } from "@/lib/mock/types"
import { lngLatToWorkspace, workspaceToLngLat } from "@/features/map/map.utils"

function ensureVertexLayer(map: MapLibreMap, color: string) {
  if (map.getSource(MAP_SOURCE.vertices)) return
  map.addSource(MAP_SOURCE.vertices, {
    type: "geojson",
    data: { type: "FeatureCollection", features: [] },
  })
  map.addLayer({
    id: MAP_LAYER.vertices,
    type: "circle",
    source: MAP_SOURCE.vertices,
    paint: {
      "circle-radius": 7,
      "circle-color": "#ffffff",
      "circle-stroke-width": 2.5,
      "circle-stroke-color": color,
    },
  })
}

function pointsToVertexGeo(points: Vec2[], color: string): FeatureCollection<Point> {
  return {
    type: "FeatureCollection",
    features: points.map((p, index) => ({
      type: "Feature",
      id: index,
      properties: { index, color },
      geometry: {
        type: "Point",
        coordinates: workspaceToLngLat(p),
      },
    })),
  }
}

export function ZoneVertexLayer({
  points,
  enabled,
  color = "#2F6FED",
  onPointsChange,
}: {
  points: Vec2[]
  enabled: boolean
  color?: string
  onPointsChange: (points: Vec2[]) => void
}) {
  const { map, ready } = useMineMap()
  const dragIndex = useRef<number | null>(null)
  const pointsRef = useRef(points)
  pointsRef.current = points

  const geo = useMemo(() => pointsToVertexGeo(points, color), [points, color])

  useEffect(() => {
    if (!map || !ready) return
    ensureVertexLayer(map, color)
    map.setPaintProperty(MAP_LAYER.vertices, "circle-stroke-color", color)
    const src = map.getSource(MAP_SOURCE.vertices) as GeoJSONSource | undefined
    src?.setData(geo)
    const visibility = enabled && points.length > 0 ? "visible" : "none"
    if (map.getLayer(MAP_LAYER.vertices)) {
      map.setLayoutProperty(MAP_LAYER.vertices, "visibility", visibility)
    }
  }, [map, ready, geo, color, enabled, points.length])

  useEffect(() => {
    if (!map || !ready || !enabled || points.length === 0) return

    const onMouseDown = (e: MapLayerMouseEvent) => {
      const f = e.features?.[0]
      const index = f?.properties?.index as number | undefined
      if (index === undefined) return
      dragIndex.current = index
      map.getCanvas().style.cursor = "grabbing"
      map.dragPan.disable()
      e.preventDefault()
    }

    const onMouseMove = (e: MapMouseEvent) => {
      if (dragIndex.current === null) return
      const idx = dragIndex.current
      const next = [...pointsRef.current]
      next[idx] = lngLatToWorkspace([e.lngLat.lng, e.lngLat.lat])
      onPointsChange(next)
    }

    const onMouseUp = () => {
      if (dragIndex.current !== null) {
        dragIndex.current = null
        map.getCanvas().style.cursor = "grab"
        map.dragPan.enable()
      }
    }

    const onEnter = () => {
      if (dragIndex.current === null) map.getCanvas().style.cursor = "grab"
    }
    const onLeave = () => {
      if (dragIndex.current === null) map.getCanvas().style.cursor = ""
    }

    map.on("mousedown", MAP_LAYER.vertices, onMouseDown)
    map.on("mousemove", onMouseMove)
    map.on("mouseup", onMouseUp)
    map.on("mouseenter", MAP_LAYER.vertices, onEnter)
    map.on("mouseleave", MAP_LAYER.vertices, onLeave)

    return () => {
      map.off("mousedown", MAP_LAYER.vertices, onMouseDown)
      map.off("mousemove", onMouseMove)
      map.off("mouseup", onMouseUp)
      map.off("mouseenter", MAP_LAYER.vertices, onEnter)
      map.off("mouseleave", MAP_LAYER.vertices, onLeave)
      map.getCanvas().style.cursor = ""
      map.dragPan.enable()
    }
  }, [map, ready, enabled, points.length, onPointsChange])

  return null
}
