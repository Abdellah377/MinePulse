import { useEffect, useRef } from "react"
import type { FeatureCollection, Point } from "geojson"
import {
  Popup,
  type GeoJSONSource,
  type Map as MapLibreMap,
  type MapLayerMouseEvent,
} from "maplibre-gl"

import { useMineMap } from "@/components/map/MineMapContext"
import { EQUIPMENT_ICON_IDS, EQUIPMENT_MAP_STYLE } from "@/features/map/map.constants"
import { equipmentPopupHtml } from "@/features/map/map.utils"
import { MAP_LAYER, MAP_SOURCE } from "@/features/map/map.types"
import type { EquipmentFeatureProps } from "@/features/map/map.types"

function syncEquipmentIconLayout(map: MapLibreMap) {
  if (!map.getLayer(MAP_LAYER.equipment)) return
  map.setLayoutProperty(MAP_LAYER.equipment, "icon-rotate", 0)
  map.setLayoutProperty(MAP_LAYER.equipment, "icon-rotation-alignment", "viewport")
  map.setLayoutProperty(MAP_LAYER.equipment, "icon-keep-upright", true)
  map.setLayoutProperty(MAP_LAYER.equipment, "icon-pitch-alignment", "viewport")
  if (map.getLayer(MAP_LAYER.equipmentLabel)) {
    map.setLayoutProperty(MAP_LAYER.equipmentLabel, "text-rotation-alignment", "viewport")
    map.setLayoutProperty(MAP_LAYER.equipmentLabel, "text-keep-upright", true)
    map.setLayoutProperty(MAP_LAYER.equipmentLabel, "text-pitch-alignment", "viewport")
  }
}

function ensureEquipmentLayers(map: MapLibreMap) {
  if (map.getSource(MAP_SOURCE.equipment)) {
    syncEquipmentIconLayout(map)
    return
  }
  map.addSource(MAP_SOURCE.equipment, {
    type: "geojson",
    data: { type: "FeatureCollection", features: [] },
  })

  map.addLayer({
    id: MAP_LAYER.equipmentHaloOuter,
    type: "circle",
    source: MAP_SOURCE.equipment,
    paint: {
      "circle-radius": [
        "case",
        ["get", "selected"],
        EQUIPMENT_MAP_STYLE.haloOuterRadiusSelected,
        EQUIPMENT_MAP_STYLE.haloOuterRadius,
      ],
      "circle-color": ["get", "stateColor"],
      "circle-opacity": ["case", ["get", "selected"], 0.12, 0.06],
      "circle-stroke-width": ["case", ["get", "selected"], 2, 1],
      "circle-stroke-color": ["get", "stateColor"],
      "circle-stroke-opacity": ["case", ["get", "selected"], 0.45, 0.2],
    },
  })

  map.addLayer({
    id: MAP_LAYER.equipmentHalo,
    type: "circle",
    source: MAP_SOURCE.equipment,
    paint: {
      "circle-radius": [
        "case",
        ["get", "selected"],
        EQUIPMENT_MAP_STYLE.haloRadiusSelected,
        EQUIPMENT_MAP_STYLE.haloRadius,
      ],
      "circle-color": ["get", "stateColor"],
      "circle-opacity": ["case", ["get", "selected"], 0.28, 0.18],
      "circle-stroke-width": ["case", ["get", "selected"], 2.5, 1.75],
      "circle-stroke-color": ["get", "stateColor"],
      "circle-stroke-opacity": 0.85,
    },
  })

  map.addLayer({
    id: MAP_LAYER.equipment,
    type: "symbol",
    source: MAP_SOURCE.equipment,
    layout: {
      "icon-image": [
        "match",
        ["get", "type"],
        "haul_truck",
        EQUIPMENT_ICON_IDS.haul_truck,
        "excavator",
        EQUIPMENT_ICON_IDS.excavator,
        "loader",
        EQUIPMENT_ICON_IDS.loader,
        "dozer",
        EQUIPMENT_ICON_IDS.dozer,
        "drill",
        EQUIPMENT_ICON_IDS.drill,
        "grader",
        EQUIPMENT_ICON_IDS.grader,
        "water_truck",
        EQUIPMENT_ICON_IDS.water_truck,
        "light_vehicle",
        EQUIPMENT_ICON_IDS.light_vehicle,
        EQUIPMENT_ICON_IDS.other,
      ],
      "icon-size": [
        "case",
        ["get", "selected"],
        EQUIPMENT_MAP_STYLE.iconSizeSelected,
        EQUIPMENT_MAP_STYLE.iconSize,
      ],
      "icon-allow-overlap": true,
      "icon-ignore-placement": true,
      // Side-view assets — never rotate/flip with heading (looks mirrored on map)
      "icon-rotate": 0,
      "icon-rotation-alignment": "viewport",
      "icon-keep-upright": true,
      "icon-pitch-alignment": "viewport",
    },
  })

  map.addLayer({
    id: MAP_LAYER.equipmentLabel,
    type: "symbol",
    source: MAP_SOURCE.equipment,
    layout: {
      "text-field": ["get", "code"],
      "text-size": [
        "case",
        ["get", "selected"],
        EQUIPMENT_MAP_STYLE.labelSizeSelected,
        EQUIPMENT_MAP_STYLE.labelSize,
      ],
      "text-offset": EQUIPMENT_MAP_STYLE.labelOffset,
      "text-font": ["Noto Sans Regular"],
      "text-allow-overlap": true,
      "text-optional": true,
      "text-rotation-alignment": "viewport",
      "text-keep-upright": true,
      "text-pitch-alignment": "viewport",
    },
    paint: {
      "text-color": "#ffffff",
      "text-halo-color": "#1c1d21",
      "text-halo-width": 2,
    },
    filter: [
      "any",
      ["get", "selected"],
      [">=", ["zoom"], EQUIPMENT_MAP_STYLE.labelMinZoom],
    ],
  })
}

export function EquipmentLayer({
  data,
  visible,
  interactive = true,
  onEquipmentClick,
  onEquipmentHover,
}: {
  data: FeatureCollection<Point, EquipmentFeatureProps>
  visible: boolean
  interactive?: boolean
  onEquipmentClick?: (id: string) => void
  onEquipmentHover?: (id: string | null) => void
}) {
  const { map, ready } = useMineMap()
  const popupRef = useRef<Popup | null>(null)

  useEffect(() => {
    if (!map || !ready) return
    ensureEquipmentLayers(map)
    const src = map.getSource(MAP_SOURCE.equipment) as GeoJSONSource | undefined
    src?.setData(data)
    for (const id of [
      MAP_LAYER.equipmentHaloOuter,
      MAP_LAYER.equipmentHalo,
      MAP_LAYER.equipment,
      MAP_LAYER.equipmentLabel,
    ]) {
      if (map.getLayer(id)) {
        map.setLayoutProperty(id, "visibility", visible ? "visible" : "none")
      }
    }
  }, [map, ready, data, visible])

  useEffect(() => {
    if (!map || !ready || !interactive) return

    if (!popupRef.current) {
      popupRef.current = new Popup({
        closeButton: false,
        closeOnClick: false,
        offset: 14,
        className: "mp-eq-popup",
      })
    }
    const popup = popupRef.current

    const onClick = (e: MapLayerMouseEvent) => {
      e.originalEvent.stopPropagation()
      const id = e.features?.[0]?.properties?.id as string | undefined
      if (id) onEquipmentClick?.(id)
    }

    const onMove = (e: MapLayerMouseEvent) => {
      const f = e.features?.[0]
      if (!f?.properties) return
      const props = f.properties as unknown as EquipmentFeatureProps
      onEquipmentHover?.(props.id)
      popup
        .setLngLat((f.geometry as Point).coordinates as [number, number])
        .setHTML(equipmentPopupHtml(props))
        .addTo(map)
      map.getCanvas().style.cursor = "pointer"
    }

    const onLeave = () => {
      onEquipmentHover?.(null)
      popup.remove()
      map.getCanvas().style.cursor = ""
    }

    map.on("click", MAP_LAYER.equipment, onClick)
    map.on("click", MAP_LAYER.equipmentHaloOuter, onClick)
    map.on("click", MAP_LAYER.equipmentHalo, onClick)
    map.on("mousemove", MAP_LAYER.equipment, onMove)
    map.on("mouseleave", MAP_LAYER.equipment, onLeave)

    return () => {
      map.off("click", MAP_LAYER.equipment, onClick)
      map.off("click", MAP_LAYER.equipmentHaloOuter, onClick)
      map.off("click", MAP_LAYER.equipmentHalo, onClick)
      map.off("mousemove", MAP_LAYER.equipment, onMove)
      map.off("mouseleave", MAP_LAYER.equipment, onLeave)
      popup.remove()
    }
  }, [map, ready, interactive, onEquipmentClick, onEquipmentHover])

  return null
}
