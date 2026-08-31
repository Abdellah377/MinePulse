import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { Search, Pencil, User, MapPin, AlertTriangle } from "lucide-react"
import type { Map as MapLibreMap } from "maplibre-gl"

import {
  useOpsStore,
  useSiteScopedEquipment,
  useSiteScopedRoutes,
  useSiteScopedZones,
} from "@/lib/store/useOpsStore"
import { useUiStore } from "@/lib/store/useUiStore"
import {
  EQUIPMENT_TYPE_LABEL,
  FILM_STATE_GROUP,
  FILM_STATE_GROUP_LABEL,
  ZONE_TYPE_LABEL,
} from "@/lib/mock/types"
import type { EquipmentType, FilmStateGroup, RoutePath, Vec2, Zone } from "@/lib/mock/types"
import { STATE_CONFIG } from "@/lib/status"
import { EquipmentTypeIcon } from "@/components/equipment/EquipmentTypeIcon"
import { cn } from "@/lib/utils"
import { inspecteurInsight } from "@/lib/ai/placeholders"
import { AiSlot } from "@/components/ai/AiSlot"
import { FilterDrawer } from "@/components/shared/FilterDrawer"
import { PeriodFilters } from "@/components/shared/PeriodFilters"
import { StatusLegend } from "@/components/shared/StatusLegend"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { MineMap } from "@/components/map/MineMap"
import { useMineMap } from "@/components/map/MineMapContext"
import { EquipmentLayer } from "@/components/map/EquipmentLayer"
import { OperationalZonesLayer } from "@/components/map/OperationalZonesLayer"
import { HaulRoadsLayer } from "@/components/map/HaulRoadsLayer"
import { RecentPathLayer } from "@/components/map/RecentPathLayer"
import { ZoneDraftLayer } from "@/components/map/ZoneDraftLayer"
import { ZoneVertexLayer } from "@/components/map/ZoneVertexLayer"
import { MapControls } from "@/components/map/MapControls"
import { MapLegend } from "@/components/map/MapLegend"
import {
  ZoneEditorToolbar,
  ZoneListPanel,
  ZonePropertiesPanel,
  type ZoneDraft,
} from "@/components/map/ZoneEditorPanel"
import {
  RoadEditorToolbar,
  RoadListPanel,
  RoadPropertiesPanel,
  emptyRoadDraft,
  type RoadDraft,
} from "@/components/map/RoadEditorPanel"
import { DEFAULT_BASEMAP, ROUTES_STORAGE_KEY, ZONES_STORAGE_KEY } from "@/features/map/map.constants"
import type { BasemapId, MapTool } from "@/features/map/map.types"
import {
  draftLngLatToGeoJSON,
  equipmentToGeoJSON,
  fitBoundsFromEquipment,
  fitBoundsFromZone,
  lngLatToWorkspace,
  recentPathToGeoJSON,
  routesToGeoJSON,
  workspaceToLngLat,
  zonesToGeoJSON,
} from "@/features/map/map.utils"
import {
  avgWaitInZone,
  inferEquipmentContext,
  zoneConditionLabel,
} from "@/features/map/map.geo"
import { buildRecentTrail, useMapLiveSimulation } from "@/features/map/map.simulation"
import { useApiMode, createRoad, createZone, deleteRoad, deleteZone, patchRoad, patchZone } from "@/lib/api/client"
import { ROAD_STATUS_LABEL, ROAD_STATUS_REASON_LABEL, roadStatus } from "@/lib/map/roadNetwork"
import {
  canSaveRoadTrace,
  copyVertices,
  geometryToPersist,
  insertMidpointOnLongestSegment,
  polylineDistanceKm,
  removeLastVertex,
} from "@/lib/map/roadGeometry"
import { ROAD_DRAFT_COLOR } from "@/lib/map/roadStyle"
import { withoutMatchingError } from "@/lib/store/apiSync"
import {
  mapCameraForEquipment,
  mapFocusEpoch,
} from "@/features/map/map.focus"

const ALL_TYPES = Object.keys(EQUIPMENT_TYPE_LABEL) as EquipmentType[]
const ALL_GROUPS = Object.keys(FILM_STATE_GROUP_LABEL) as FilmStateGroup[]

function emptyDraft(): ZoneDraft {
  return { name: "Nouvelle zone", type: "chargement", color: "#2F6FED", description: "", capacity: 2 }
}

function MapFlyTo({
  equipmentId,
  equipment,
  focusRequestId,
}: {
  equipmentId: string | null
  equipment: ReturnType<typeof useSiteScopedEquipment>
  focusRequestId?: number | string | null
}) {
  const { map, ready } = useMineMap()
  const lastEpoch = useRef<string | null>(null)
  const target = equipment.find((e) => e.id === equipmentId)
  const camera = mapCameraForEquipment(target)
  const cameraRef = useRef(camera)
  cameraRef.current = camera
  const hasPosition = camera != null
  useEffect(() => {
    if (!map || !ready || !equipmentId) return
    const next = cameraRef.current
    const epoch = mapFocusEpoch(equipmentId, next != null, focusRequestId)
    if (!epoch || epoch === lastEpoch.current || !next) return
    lastEpoch.current = epoch
    map.easeTo({
      center: next.center,
      zoom: Math.max(map.getZoom(), next.zoom),
      duration: 600,
    })
  }, [map, ready, equipmentId, focusRequestId, hasPosition])
  return null
}

function FitOnReady({
  equipment,
  skip,
}: {
  equipment: ReturnType<typeof useSiteScopedEquipment>
  skip: boolean
}) {
  const { map, ready } = useMineMap()
  const didFit = useRef(false)
  useEffect(() => {
    if (!map || !ready || didFit.current) return
    if (skip) {
      didFit.current = true
      return
    }
    const bounds = fitBoundsFromEquipment(equipment)
    if (!bounds) return
    map.fitBounds(bounds, { padding: 64, duration: 0, maxZoom: 15.5 })
    didFit.current = true
  }, [map, ready, equipment, skip])
  return null
}

function FlyToZone({ zone }: { zone: Zone | null }) {
  const { map, ready } = useMineMap()
  const lastId = useRef<string | null>(null)

  useEffect(() => {
    if (!map || !ready || !zone) return
    if (lastId.current === zone.id) return
    const bounds = fitBoundsFromZone(zone)
    if (!bounds) return
    lastId.current = zone.id
    map.fitBounds(bounds, { padding: 80, duration: 500, maxZoom: 17 })
  }, [map, ready, zone])

  return null
}

/**
 * Single source of truth for locking map navigation while drawing/editing a zone.
 * Kept separate from ZoneDraftLayer/ZoneVertexLayer so their effect churn (data,
 * color, tool changes) never races the pan/zoom lock and silently re-enables it.
 *
 * Disables EVERY camera-interaction handler, not just dragPan/doubleClickZoom:
 * trackpads routinely emit wheel/gesture events (pinch, two-finger pan) even
 * during what feels like a single tap-to-click, and scrollZoom/touchZoomRotate
 * left enabled will happily pan or zoom the map underneath the crosshair.
 */
function MapInteractionLock({ mode }: { mode: "draw" | "none" }) {
  const { map, ready } = useMineMap()

  useEffect(() => {
    if (!map || !ready) return

    const handlers = [
      map.dragPan,
      map.dragRotate,
      map.doubleClickZoom,
      map.boxZoom,
      map.scrollZoom,
      map.touchZoomRotate,
      map.touchPitch,
      map.keyboard,
    ].filter(Boolean)

    if (mode === "draw") {
      for (const h of handlers) h.disable()
      map.getCanvas().style.cursor = "crosshair"
      // eslint-disable-next-line no-console
      console.debug("[MapInteractionLock] drawing lock ENGAGED", {
        dragPan: map.dragPan.isEnabled(),
        doubleClickZoom: map.doubleClickZoom.isEnabled(),
        scrollZoom: map.scrollZoom.isEnabled(),
      })
    }

    return () => {
      for (const h of handlers) h.enable()
      map.getCanvas().style.cursor = ""
    }
  }, [map, ready, mode])

  return null
}

export default function Carte({ tab }: Partial<import("@/components/workspace/WorkspaceHost").WorkspacePanelProps> = {}) {
  const equipment = useSiteScopedEquipment()
  const zones = useSiteScopedZones()
  const routes = useSiteScopedRoutes()
  const alerts = useOpsStore((s) => s.alerts)
  const selectedSiteId = useOpsStore((s) => s.selectedSiteId)
  const selectedShiftId = useOpsStore((s) => s.selectedShiftId)
  const setZones = useOpsStore((s) => s.setZones)
  const setRoutes = useOpsStore((s) => s.setRoutes)
  const openEquipmentDrawer = useUiStore((s) => s.openEquipmentDrawer)

  const [basemap, setBasemap] = useState<BasemapId>(DEFAULT_BASEMAP)
  const [typeFilter, setTypeFilter] = useState<Set<EquipmentType>>(new Set(ALL_TYPES))
  const [groupFilter, setGroupFilter] = useState<Set<FilmStateGroup>>(new Set(ALL_GROUPS))
  const [zoneFilter, setZoneFilter] = useState<string>("all")
  const [search, setSearch] = useState("")
  const [showZonesLayer, setShowZonesLayer] = useState(true)
  const [showRoadsLayer, setShowRoadsLayer] = useState(false)
  const [showEquipmentLayer, setShowEquipmentLayer] = useState(true)
  const [onlyActiveEvents, setOnlyActiveEvents] = useState(false)
  const [showRecentPath, setShowRecentPath] = useState(false)

  const [selectedEquipmentId, setSelectedEquipmentId] = useState<string | null>(tab?.context.equipmentId ?? null)
  const [selectedZoneId, setSelectedZoneId] = useState<string | null>(tab?.context.zoneId ?? null)
  const [selectedRoadId, setSelectedRoadId] = useState<string | null>(null)
  useEffect(() => {
    setSelectedEquipmentId(tab?.context.equipmentId ?? null)
    setSelectedZoneId(tab?.context.zoneId ?? null)
  }, [tab?.context.equipmentId, tab?.context.zoneId])

  const [configMode, setConfigMode] = useState(false)
  const [configTab, setConfigTab] = useState<"zones" | "routes">("zones")
  const [activeTool, setActiveTool] = useState<MapTool>("select")
  const [draftPoints, setDraftPoints] = useState<Vec2[]>([])
  const [draftLngLat, setDraftLngLat] = useState<[number, number][]>([])
  const [draft, setDraft] = useState<ZoneDraft | null>(null)
  const [roadDraft, setRoadDraft] = useState<RoadDraft | null>(null)
  const [isCreating, setIsCreating] = useState(false)
  const [editingVertices, setEditingVertices] = useState<Vec2[] | null>(null)
  const [roadEditingVertices, setRoadEditingVertices] = useState<Vec2[] | null>(null)
  const [focusZoneId, setFocusZoneId] = useState<string | null>(null)

  useMapLiveSimulation(!configMode && !useApiMode)

  // Prototype zone/route persistence (mock mode only)
  useEffect(() => {
    if (useApiMode) return
    try {
      const raw = localStorage.getItem(ZONES_STORAGE_KEY)
      if (raw) {
        const saved = JSON.parse(raw) as Zone[]
        if (Array.isArray(saved) && saved.length > 0) {
          setZones((current) => {
            const byId = new Map(current.map((z) => [z.id, z]))
            for (const z of saved) {
              if (z.siteId === selectedSiteId) byId.set(z.id, z)
            }
            return Array.from(byId.values())
          })
        }
      }
      const roadsRaw = localStorage.getItem(ROUTES_STORAGE_KEY)
      if (roadsRaw) {
        const savedRoads = JSON.parse(roadsRaw) as RoutePath[]
        if (Array.isArray(savedRoads) && savedRoads.length > 0) {
          setRoutes((current) => {
            const byId = new Map(current.map((r) => [r.id, r]))
            for (const r of savedRoads) {
              if (r.siteId === selectedSiteId) byId.set(r.id, r)
            }
            return Array.from(byId.values())
          })
        }
      }
    } catch {
      /* ignore corrupt prototype store */
    }
    // once on mount
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const zoneApiCtx = useMemo(
    () => ({ siteCode: selectedSiteId, shiftId: selectedShiftId }),
    [selectedSiteId, selectedShiftId]
  )

  const persistZones = useCallback(
    (updater: (zones: Zone[]) => Zone[]) => {
      setZones((zs) => {
        const next = updater(zs)
        if (!useApiMode) {
          try {
            localStorage.setItem(
              ZONES_STORAGE_KEY,
              JSON.stringify(next.filter((z) => z.siteId === selectedSiteId))
            )
          } catch {
            /* quota */
          }
        }
        return next
      })
    },
    [setZones, selectedSiteId]
  )

  const persistRoutes = useCallback(
    (updater: (routes: RoutePath[]) => RoutePath[]) => {
      setRoutes((rs) => {
        const next = updater(rs)
        if (!useApiMode) {
          try {
            localStorage.setItem(
              ROUTES_STORAGE_KEY,
              JSON.stringify(next.filter((r) => r.siteId === selectedSiteId))
            )
          } catch {
            /* quota */
          }
        }
        return next
      })
    },
    [setRoutes, selectedSiteId]
  )

  const removeZone = useCallback(
    async (id: string) => {
      if (useApiMode) {
        try {
          await deleteZone(id, zoneApiCtx)
          setZones((zs) => zs.filter((z) => z.id !== id))
          useOpsStore.setState((s) => ({
            apiPollError: withoutMatchingError(s.apiPollError, [
              "Échec enregistrement zone",
              "Échec suppression zone",
            ]),
          }))
        } catch {
          useOpsStore.setState({ apiPollError: "Échec suppression zone" })
        }
        return
      }
      persistZones((zs) => zs.filter((z) => z.id !== id))
    },
    [persistZones, setZones, zoneApiCtx]
  )

  const removeRoad = useCallback(
    async (id: string) => {
      if (useApiMode) {
        try {
          await deleteRoad(id, zoneApiCtx)
          setRoutes((rs) => rs.filter((r) => r.id !== id))
          useOpsStore.setState((s) => ({
            apiPollError: withoutMatchingError(s.apiPollError, [
              "Échec enregistrement route",
              "Échec suppression route",
            ]),
          }))
        } catch {
          useOpsStore.setState({ apiPollError: "Échec suppression route" })
        }
        return
      }
      persistRoutes((rs) => rs.filter((r) => r.id !== id))
    },
    [persistRoutes, setRoutes, zoneApiCtx]
  )

  const equipmentWithEvents = useMemo(() => {
    const ids = new Set(
      alerts.filter((a) => a.status !== "resolved" && a.equipmentId).map((a) => a.equipmentId!)
    )
    return ids
  }, [alerts])

  const filteredEquipment = useMemo(() => {
    const q = search.trim().toLowerCase()
    return equipment.filter((e) => {
      if (!typeFilter.has(e.type)) return false
      if (!groupFilter.has(FILM_STATE_GROUP[e.state])) return false
      if (zoneFilter !== "all" && e.zoneId !== zoneFilter) return false
      if (onlyActiveEvents && !equipmentWithEvents.has(e.id)) return false
      if (q && !e.code.toLowerCase().includes(q) && !e.model.toLowerCase().includes(q)) return false
      return true
    })
  }, [equipment, typeFilter, groupFilter, search, zoneFilter, onlyActiveEvents, equipmentWithEvents])

  const selectedEquipment = equipment.find((e) => e.id === selectedEquipmentId) ?? null
  const selectedZone = zones.find((z) => z.id === selectedZoneId) ?? null
  const selectedRoad = routes.find((r) => r.id === selectedRoadId) ?? null

  const equipmentGeo = useMemo(
    () => equipmentToGeoJSON(showEquipmentLayer ? filteredEquipment : [], zones, selectedEquipmentId),
    [filteredEquipment, zones, selectedEquipmentId, showEquipmentLayer]
  )
  const zonesGeo = useMemo(
    () => zonesToGeoJSON(zones, equipment, selectedZoneId),
    [zones, equipment, selectedZoneId]
  )
  const roadsGeo = useMemo(() => {
    const display =
      roadEditingVertices && selectedRoadId
        ? routes.map((r) => (r.id === selectedRoadId ? { ...r, points: roadEditingVertices } : r))
        : routes
    return routesToGeoJSON(display, selectedRoadId)
  }, [routes, selectedRoadId, roadEditingVertices])
  const draftGeo = useMemo(
    () => draftLngLatToGeoJSON(draftLngLat, { polygon: configTab === "zones" }),
    [draftLngLat, configTab]
  )
  const recentGeo = useMemo(() => {
    if (useApiMode || !showRecentPath || !selectedEquipment) {
      return { type: "FeatureCollection" as const, features: [] }
    }
    return recentPathToGeoJSON(buildRecentTrail(selectedEquipment, routes))
  }, [showRecentPath, selectedEquipment, routes])

  const pipContext = useMemo(() => {
    if (useApiMode || !selectedEquipment) return null
    return inferEquipmentContext(selectedEquipment, zones)
  }, [selectedEquipment, zones])

  function toggleType(t: EquipmentType) {
    setTypeFilter((prev) => {
      const next = new Set(prev)
      if (next.has(t)) next.delete(t)
      else next.add(t)
      return next
    })
  }

  function toggleGroup(g: FilmStateGroup) {
    setGroupFilter((prev) => {
      const next = new Set(prev)
      if (next.has(g)) next.delete(g)
      else next.add(g)
      return next
    })
  }

  function resetDraftState() {
    setDraft(null)
    setRoadDraft(null)
    setIsCreating(false)
    setDraftPoints([])
    setDraftLngLat([])
    setEditingVertices(null)
    setRoadEditingVertices(null)
    setActiveTool("select")
  }

  function enterConfigMode(tab: "zones" | "routes" = "zones") {
    setConfigMode(true)
    setConfigTab(tab)
    setActiveTool("select")
    setSelectedEquipmentId(null)
    setShowRecentPath(false)
    resetDraftState()
  }

  function exitConfigMode() {
    if ((isCreating || editingVertices || roadEditingVertices) && !window.confirm("Quitter la configuration ? Des modifications non enregistrées seront perdues.")) {
      return
    }
    setConfigMode(false)
    setSelectedZoneId(null)
    setSelectedRoadId(null)
    resetDraftState()
  }

  function selectZoneForEdit(id: string) {
    const z = zones.find((zz) => zz.id === id)
    if (!z) return
    setSelectedZoneId(id)
    setSelectedRoadId(null)
    setIsCreating(false)
    setDraftPoints([])
    setDraftLngLat([])
    setRoadDraft(null)
    setRoadEditingVertices(null)
    setDraft({
      name: z.name,
      type: z.type,
      color: z.color,
      description: z.description,
      capacity: z.capacity,
    })
    if (activeTool === "vertex") {
      setEditingVertices([...z.points])
    } else {
      setEditingVertices(null)
    }
  }

  function selectRoadForEdit(id: string) {
    const r = routes.find((rr) => rr.id === id)
    if (!r) return
    setSelectedRoadId(id)
    setSelectedZoneId(null)
    setSelectedEquipmentId(null)
    setIsCreating(false)
    setDraftPoints([])
    setDraftLngLat([])
    setDraft(null)
    setEditingVertices(null)
    if (activeTool === "vertex") {
      setRoadEditingVertices(copyVertices(r.points))
    } else {
      setRoadEditingVertices(null)
    }
    setRoadDraft({
      code: r.id,
      name: r.name ?? r.id,
      fromZoneId: r.fromZoneId,
      toZoneId: r.toZoneId,
      distanceKm: r.distanceKm,
      speedLimitKmh: r.speedLimitKmh ?? null,
      description: r.description ?? "",
      status: roadStatus(r),
      statusReason: r.statusReason ?? null,
      statusNote: r.statusNote ?? "",
    })
  }

  function startNewZone() {
    setSelectedZoneId(null)
    setSelectedRoadId(null)
    setRoadDraft(null)
    setIsCreating(true)
    setActiveTool("polygon")
    setDraftPoints([])
    setDraftLngLat([])
    setEditingVertices(null)
    setRoadEditingVertices(null)
    setDraft(emptyDraft())
  }

  function startNewRoad() {
    setSelectedRoadId(null)
    setSelectedZoneId(null)
    setDraft(null)
    setIsCreating(true)
    setActiveTool("polyline")
    setDraftPoints([])
    setDraftLngLat([])
    setEditingVertices(null)
    setRoadEditingVertices(null)
    setRoadDraft(emptyRoadDraft())
  }

  function handleToolChange(tool: MapTool) {
    setActiveTool(tool)
    if (tool === "polygon") {
      startNewZone()
      return
    }
    if (tool === "polyline") {
      startNewRoad()
      return
    }
    setIsCreating(false)
    setDraftPoints([])
    setDraftLngLat([])
    if (tool === "vertex") {
      if (configTab === "routes") {
        setEditingVertices(null)
        if (selectedRoadId) {
          const r = routes.find((rr) => rr.id === selectedRoadId)
          if (r) setRoadEditingVertices(copyVertices(r.points))
        } else {
          setRoadEditingVertices(null)
        }
        return
      }
      setRoadEditingVertices(null)
      if (selectedZoneId) {
        const z = zones.find((zz) => zz.id === selectedZoneId)
        if (z) setEditingVertices([...z.points])
      } else {
        setEditingVertices(null)
      }
      return
    }
    setEditingVertices(null)
    setRoadEditingVertices(null)
  }

  const handleCanvasClick = useCallback(
    (lngLat: [number, number]) => {
      if (isCreating && (activeTool === "polygon" || activeTool === "polyline")) {
        setDraftLngLat((pts) => [...pts, lngLat])
        setDraftPoints((pts) => [...pts, lngLatToWorkspace(lngLat)])
      }
    },
    [isCreating, activeTool]
  )

  function undoLastPoint() {
    setDraftLngLat((pts) => pts.slice(0, -1))
    setDraftPoints((pts) => pts.slice(0, -1))
  }

  function handleZoneClick(id: string) {
    if (configMode) {
      if (configTab !== "zones") return
      if (activeTool === "delete") {
        if (!window.confirm("Supprimer cette zone ?")) return
        void removeZone(id)
        if (selectedZoneId === id) {
          setSelectedZoneId(null)
          setDraft(null)
        }
        return
      }
      selectZoneForEdit(id)
    } else {
      setSelectedEquipmentId(null)
      setSelectedRoadId(null)
      setSelectedZoneId(id)
    }
  }

  function handleRoadClick(id: string) {
    if (configMode) {
      if (configTab !== "routes") return
      if (activeTool === "delete") {
        if (!window.confirm("Supprimer cette route ?")) return
        void removeRoad(id)
        if (selectedRoadId === id) {
          setSelectedRoadId(null)
          setRoadDraft(null)
        }
        return
      }
      selectRoadForEdit(id)
      return
    }
    setSelectedEquipmentId(null)
    setSelectedZoneId(null)
    setSelectedRoadId(id)
  }

  function handleEquipmentClick(id: string) {
    if (configMode) return
    setSelectedZoneId(null)
    setSelectedRoadId(null)
    setSelectedEquipmentId(id)
    openEquipmentDrawer(id)
  }

  async function handleSaveDraft() {
    if (!draft) return
    if (isCreating) {
      if (draftPoints.length < 3) return
      const points = draftPoints.map((p) => ({ x: p.x, y: p.y }))
      if (useApiMode) {
        const code = `zone-${crypto.randomUUID().slice(0, 8)}`
        try {
          const created = await createZone(
            {
              code,
              name: draft.name.trim() || "Nouvelle zone",
              type: draft.type,
              points,
              color: draft.color,
              description: draft.description,
              capacity: draft.capacity ?? undefined,
            },
            zoneApiCtx
          )
          setZones((zs) => [...zs, created])
          useOpsStore.setState((s) => ({
            apiPollError: withoutMatchingError(s.apiPollError, "Échec enregistrement zone"),
          }))
          setIsCreating(false)
          setDraftPoints([])
          setDraftLngLat([])
          setSelectedZoneId(created.id)
          setFocusZoneId(created.id)
          setActiveTool("select")
          setDraft({
            name: created.name,
            type: created.type,
            color: created.color,
            description: created.description,
            capacity: created.capacity,
          })
        } catch {
          useOpsStore.setState({ apiPollError: "Échec enregistrement zone" })
        }
        return
      }
      const newZone: Zone = {
        id: `${selectedSiteId}-zone-${crypto.randomUUID().slice(0, 8)}`,
        name: draft.name.trim() || "Nouvelle zone",
        type: draft.type,
        points: draftPoints.map((p) => ({ x: p.x, y: p.y })),
        ringLngLat: draftLngLat.map(([lng, lat]) => [lng, lat] as [number, number]),
        color: draft.color,
        description: draft.description,
        capacity: draft.capacity,
        siteId: selectedSiteId,
      }
      persistZones((zs) => [...zs, newZone])
      setIsCreating(false)
      setDraftPoints([])
      setDraftLngLat([])
      setSelectedZoneId(newZone.id)
      setFocusZoneId(newZone.id)
      setActiveTool("select")
      setDraft({
        name: newZone.name,
        type: newZone.type,
        color: newZone.color,
        description: newZone.description,
        capacity: newZone.capacity,
      })
    } else if (selectedZoneId) {
      if (useApiMode) {
        const pts = editingVertices?.map((p) => ({ x: p.x, y: p.y }))
        try {
          const updated = await patchZone(
            selectedZoneId,
            {
              name: draft.name,
              type: draft.type,
              color: draft.color,
              description: draft.description,
              capacity: draft.capacity ?? undefined,
              ...(pts ? { points: pts } : {}),
            },
            zoneApiCtx
          )
          setZones((zs) => zs.map((z) => (z.id === selectedZoneId ? updated : z)))
          useOpsStore.setState((s) => ({
            apiPollError: withoutMatchingError(s.apiPollError, "Échec enregistrement zone"),
          }))
        } catch {
          useOpsStore.setState({ apiPollError: "Échec enregistrement zone" })
        }
        return
      }
      persistZones((zs) =>
        zs.map((z) =>
          z.id === selectedZoneId
            ? {
                ...z,
                name: draft.name,
                type: draft.type,
                color: draft.color,
                description: draft.description,
                capacity: draft.capacity,
                points: editingVertices ?? z.points,
                ringLngLat: editingVertices
                  ? editingVertices.map((p) => workspaceToLngLat(p) as [number, number])
                  : z.ringLngLat,
              }
            : z
        )
      )
    }
  }

  async function handleSaveRoad() {
    if (!roadDraft) return
    if (!canSaveRoadTrace({ isCreating, draftPoints, roadEditingVertices })) return
    const points = geometryToPersist({ isCreating, draftPoints, roadEditingVertices })
    const code = (roadDraft.code.trim() || `R-${crypto.randomUUID().slice(0, 6)}`).toUpperCase()
    const knownStatus = roadDraft.status === "UNKNOWN" ? undefined : roadDraft.status
    const payload = {
      name: roadDraft.name.trim() || code,
      fromZoneId: roadDraft.fromZoneId || undefined,
      toZoneId: roadDraft.toZoneId || undefined,
      speedLimitKmh: roadDraft.speedLimitKmh,
      description: roadDraft.description || null,
      ...(knownStatus
        ? {
            status: knownStatus,
            statusReason: knownStatus === "OPEN" ? null : roadDraft.statusReason,
            statusNote: knownStatus === "OPEN" ? null : roadDraft.statusNote || null,
          }
        : {}),
    }
    if (isCreating) {
      if (!points) return
      if (useApiMode) {
        try {
          const created = await createRoad({ code, points, ...payload }, zoneApiCtx)
          setRoutes((rs) => [...rs, created])
          useOpsStore.setState((s) => ({
            apiPollError: withoutMatchingError(s.apiPollError, "Échec enregistrement route"),
          }))
          setIsCreating(false)
          setDraftPoints([])
          setDraftLngLat([])
          setRoadEditingVertices(null)
          setSelectedRoadId(created.id)
          setActiveTool("select")
          setRoadDraft({
            ...roadDraft,
            code: created.id,
            name: created.name ?? created.id,
          })
        } catch {
          useOpsStore.setState({ apiPollError: "Échec enregistrement route" })
        }
        return
      }
      const created: RoutePath = {
        id: code,
        name: payload.name,
        fromZoneId: roadDraft.fromZoneId,
        toZoneId: roadDraft.toZoneId,
        points,
        distanceKm: polylineDistanceKm(points),
        siteId: selectedSiteId,
        status: knownStatus ?? "OPEN",
        speedLimitKmh: roadDraft.speedLimitKmh,
        description: roadDraft.description || null,
        statusReason: knownStatus === "OPEN" ? null : roadDraft.statusReason,
        statusNote: knownStatus === "OPEN" ? null : roadDraft.statusNote || null,
      }
      persistRoutes((rs) => [...rs.filter((r) => r.id !== created.id), created])
      setIsCreating(false)
      setDraftPoints([])
      setDraftLngLat([])
      setRoadEditingVertices(null)
      setSelectedRoadId(created.id)
      setActiveTool("select")
      return
    }
    if (!selectedRoadId) return
    if (useApiMode) {
      try {
        const updated = await patchRoad(
          selectedRoadId,
          {
            ...payload,
            ...(points ? { points } : {}),
          },
          zoneApiCtx
        )
        setRoutes((rs) => rs.map((r) => (r.id === selectedRoadId ? updated : r)))
        useOpsStore.setState((s) => ({
          apiPollError: withoutMatchingError(s.apiPollError, "Échec enregistrement route"),
        }))
        setRoadEditingVertices(null)
        setActiveTool("select")
      } catch {
        useOpsStore.setState({ apiPollError: "Échec enregistrement route" })
      }
      return
    }
    persistRoutes((rs) =>
      rs.map((r) =>
        r.id === selectedRoadId
          ? {
              ...r,
              name: payload.name,
              fromZoneId: roadDraft.fromZoneId,
              toZoneId: roadDraft.toZoneId,
              points: points ?? r.points,
              distanceKm: points ? polylineDistanceKm(points) : r.distanceKm,
              status: knownStatus ?? r.status,
              speedLimitKmh: roadDraft.speedLimitKmh,
              description: roadDraft.description || null,
              statusReason: knownStatus === "OPEN" ? null : roadDraft.statusReason,
              statusNote: knownStatus === "OPEN" ? null : roadDraft.statusNote || null,
            }
          : r
      )
    )
    setRoadEditingVertices(null)
    setActiveTool("select")
  }

  function handleCancelDraft() {
    setIsCreating(false)
    setDraftPoints([])
    setDraftLngLat([])
    setSelectedZoneId(null)
    setSelectedRoadId(null)
    setDraft(null)
    setRoadDraft(null)
    setEditingVertices(null)
    setRoadEditingVertices(null)
    setActiveTool("select")
  }

  function startRoadTraceEdit() {
    if (!selectedRoadId) return
    const r = routes.find((rr) => rr.id === selectedRoadId)
    if (!r) return
    setIsCreating(false)
    setDraftPoints([])
    setDraftLngLat([])
    setEditingVertices(null)
    setActiveTool("vertex")
    setRoadEditingVertices(copyVertices(r.points))
  }

  function handleDeleteZone() {
    if (!selectedZoneId) return
    if (!window.confirm("Supprimer cette zone ?")) return
    void removeZone(selectedZoneId).then(() => {
      setSelectedZoneId(null)
      setDraft(null)
      setEditingVertices(null)
    })
  }

  function handleDeleteRoad() {
    if (!selectedRoadId) return
    if (!window.confirm("Supprimer cette route ?")) return
    void removeRoad(selectedRoadId).then(() => {
      setSelectedRoadId(null)
      setRoadDraft(null)
      setRoadEditingVertices(null)
    })
  }

  function handleMapReady(map: MapLibreMap) {
    const bounds = fitBoundsFromEquipment(filteredEquipment)
    if (bounds) map.fitBounds(bounds, { padding: 64, duration: 0, maxZoom: 15.5 })
  }

  useEffect(() => {
    if (!configMode) return
    function onKey(e: KeyboardEvent) {
      const target = e.target as HTMLElement
      if (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.tagName === "SELECT")
        return
      if (e.key === "Backspace" && isCreating && draftPoints.length > 0) {
        e.preventDefault()
        undoLastPoint()
      } else if (e.key === "Backspace" && roadEditingVertices && roadEditingVertices.length > 2) {
        e.preventDefault()
        setRoadEditingVertices(removeLastVertex(roadEditingVertices))
      } else if (e.key === "Escape") {
        if (isCreating || draft || roadDraft || roadEditingVertices) handleCancelDraft()
        else exitConfigMode()
      } else if (e.key === "Enter" && isCreating && configTab === "zones" && draftPoints.length >= 3 && draft) {
        handleSaveDraft()
      } else if (e.key === "Enter" && isCreating && configTab === "routes" && draftPoints.length >= 2 && roadDraft) {
        void handleSaveRoad()
      }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps -- keyboard shortcuts for edit session
  }, [configMode, configTab, isCreating, draftPoints.length, draft, roadDraft, roadEditingVertices])

  const isEditingVertices = activeTool === "vertex" && editingVertices !== null && !isCreating
  const isEditingRoadVertices =
    activeTool === "vertex" && roadEditingVertices !== null && !isCreating && configTab === "routes"
  const roadsVisible = showRoadsLayer || (configMode && configTab === "routes")
  const drawing = isCreating && (activeTool === "polygon" || activeTool === "polyline")
  const canSaveCurrentRoad = canSaveRoadTrace({ isCreating, draftPoints, roadEditingVertices })
  const roadPointCount = isCreating
    ? draftPoints.length
    : (roadEditingVertices?.length ?? selectedRoad?.points.length ?? 0)

  return (
    <div className="flex h-full flex-col">
      {configMode && configTab === "zones" && (
        <ZoneEditorToolbar activeTool={activeTool} onToolChange={handleToolChange} />
      )}
      {configMode && configTab === "routes" && (
        <RoadEditorToolbar activeTool={activeTool} onToolChange={handleToolChange} />
      )}
      <div className="flex min-h-0 flex-1">
        {configMode ? (
          <div className="flex w-[220px] shrink-0 flex-col border-r border-border">
            <div className="flex border-b border-border">
              {(["zones", "routes"] as const).map((id) => (
                <button
                  key={id}
                  type="button"
                  onClick={() => {
                    if (isCreating || editingVertices || roadEditingVertices) {
                      if (!window.confirm("Changer d’onglet ? Le tracé en cours sera perdu.")) return
                    }
                    resetDraftState()
                    setConfigTab(id)
                    setSelectedZoneId(null)
                    setSelectedRoadId(null)
                  }}
                  className={cn(
                    "flex-1 py-2 text-[11px] font-medium",
                    configTab === id ? "border-b-2 border-accent text-accent" : "text-muted hover:text-foreground"
                  )}
                >
                  {id === "zones" ? "Zones" : "Routes"}
                </button>
              ))}
            </div>
            <div className="min-h-0 flex-1">
              {configTab === "zones" ? (
                <ZoneListPanel
                  zones={zones}
                  selectedZoneId={selectedZoneId}
                  onSelectZone={selectZoneForEdit}
                  onNewZone={startNewZone}
                  creating={isCreating}
                />
              ) : (
                <RoadListPanel
                  roads={routes}
                  selectedRoadId={selectedRoadId}
                  onSelectRoad={selectRoadForEdit}
                  onNewRoad={startNewRoad}
                  creating={isCreating}
                />
              )}
            </div>
          </div>
        ) : (
          <FilterDrawer title="Filtres" defaultCollapsed widthExpanded={200}>
            <div className="flex flex-col gap-3 p-2.5">
              <PeriodFilters className="border-b border-border pb-3" />

              <div>
                <label className="mb-1 flex items-center gap-1.5 text-[10px] font-semibold uppercase text-muted-2">
                  <Search className="size-3" />
                  Recherche
                </label>
                <Input
                  placeholder="ID engin…"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  className="h-7 rounded-md text-xs"
                />
              </div>

              <div>
                <p className="mb-1 text-[10px] font-semibold uppercase text-muted-2">Type</p>
                <div className="flex flex-col gap-0.5 border border-border bg-background">
                  {ALL_TYPES.map((t) => (
                    <label
                      key={t}
                      className="flex items-center gap-2 border-b border-border px-2 py-1.5 text-[11px] last:border-0"
                    >
                      <input
                        type="checkbox"
                        checked={typeFilter.has(t)}
                        onChange={() => toggleType(t)}
                        className="size-3.5 accent-accent"
                      />
                      {EQUIPMENT_TYPE_LABEL[t]}
                    </label>
                  ))}
                </div>
              </div>

              <div>
                <p className="mb-1 text-[10px] font-semibold uppercase text-muted-2">Statut</p>
                <div className="flex flex-col gap-0.5">
                  {ALL_GROUPS.map((g) => (
                    <label key={g} className="flex items-center gap-2 px-0.5 py-0.5 text-[11px]">
                      <input
                        type="checkbox"
                        checked={groupFilter.has(g)}
                        onChange={() => toggleGroup(g)}
                        className="size-3.5 accent-accent"
                      />
                      {FILM_STATE_GROUP_LABEL[g]}
                    </label>
                  ))}
                </div>
              </div>

              <div>
                <p className="mb-1 text-[10px] font-semibold uppercase text-muted-2">Zone</p>
                <select
                  className="h-7 w-full rounded-md border border-border bg-background px-2 text-[11px]"
                  value={zoneFilter}
                  onChange={(e) => setZoneFilter(e.target.value)}
                >
                  <option value="all">Toutes</option>
                  {zones.map((z) => (
                    <option key={z.id} value={z.id}>
                      {z.name}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <p className="mb-1 text-[10px] font-semibold uppercase text-muted-2">Couches</p>
                <div className="flex flex-col gap-1">
                  {(
                    [
                      ["Zones", showZonesLayer, () => setShowZonesLayer((v) => !v)],
                      ["Pistes", showRoadsLayer, () => setShowRoadsLayer((v) => !v)],
                      ["Engins", showEquipmentLayer, () => setShowEquipmentLayer((v) => !v)],
                    ] as const
                  ).map(([label, checked, toggle]) => (
                    <label key={label} className="flex items-center gap-2 text-[11px]">
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={toggle}
                        className="size-3.5 accent-accent"
                      />
                      {label}
                    </label>
                  ))}
                  <label className="flex items-center gap-2 text-[11px]">
                    <input
                      type="checkbox"
                      checked={onlyActiveEvents}
                      onChange={() => setOnlyActiveEvents((v) => !v)}
                      className="size-3.5 accent-accent"
                    />
                    Avec événements actifs
                  </label>
                </div>
              </div>

              <Button
                className="h-8 rounded-md text-[11px] font-semibold"
                variant="outline"
                onClick={() => {
                  setTypeFilter(new Set(ALL_TYPES))
                  setGroupFilter(new Set(ALL_GROUPS))
                  setZoneFilter("all")
                  setSearch("")
                  setOnlyActiveEvents(false)
                }}
              >
                Actualiser filtres
              </Button>
            </div>
          </FilterDrawer>
        )}

        <div className="relative min-h-0 min-w-0 flex-1 overflow-hidden">
          <MineMap
            key={basemap}
            basemap={basemap}
            onReady={handleMapReady}
            className={cn("h-full w-full", configMode && drawing && "mp-map-drawing")}
          >
            <HaulRoadsLayer
              data={roadsGeo}
              visible={roadsVisible}
              interactive={!drawing && !isEditingRoadVertices}
              onRoadClick={handleRoadClick}
            />
            <OperationalZonesLayer
              data={zonesGeo}
              visible={showZonesLayer}
              interactive={!isCreating}
              onZoneClick={handleZoneClick}
            />
            <EquipmentLayer
              data={equipmentGeo}
              visible={showEquipmentLayer && !configMode}
              interactive={!configMode}
              onEquipmentClick={handleEquipmentClick}
            />
            <RecentPathLayer data={recentGeo} visible={showRecentPath && !configMode} />
            <ZoneDraftLayer
              data={draftGeo}
              enabled={configMode && drawing}
              color={configTab === "zones" ? draft?.color : ROAD_DRAFT_COLOR}
              onMapClick={handleCanvasClick}
              onDoubleClickFinish={() => {
                /* contour closed visually — user saves from panel */
              }}
              pointCount={draftPoints.length}
            />
            <MapInteractionLock
              mode={configMode && drawing ? "draw" : "none"}
            />
            <ZoneVertexLayer
              points={isEditingRoadVertices ? (roadEditingVertices ?? []) : (editingVertices ?? [])}
              enabled={configMode && (isEditingVertices || isEditingRoadVertices)}
              color={isEditingRoadVertices ? ROAD_DRAFT_COLOR : draft?.color}
              onPointsChange={isEditingRoadVertices ? setRoadEditingVertices : setEditingVertices}
            />
            <MapFlyTo
              equipmentId={selectedEquipmentId}
              equipment={equipment}
              focusRequestId={typeof tab?.context.mapFocusAt === "number" ? tab.context.mapFocusAt : null}
            />
            <FlyToZone
              zone={
                focusZoneId ? (zones.find((z) => z.id === focusZoneId) ?? null) : null
              }
            />
            <FitOnReady
              equipment={filteredEquipment}
              skip={Boolean(selectedEquipmentId && mapCameraForEquipment(equipment.find((e) => e.id === selectedEquipmentId)))}
            />
            <MapControls
              basemap={basemap}
              onBasemapChange={setBasemap}
              configMode={configMode}
              onToggleConfig={configMode ? exitConfigMode : () => enterConfigMode(configTab)}
              fitEquipment={filteredEquipment}
            />
            {!configMode && <MapLegend showRoads={showRoadsLayer} />}
          </MineMap>

          <div className="pointer-events-none absolute right-3 top-3 z-10 rounded-md border border-warning/30 bg-warning/15 px-2.5 py-1 text-[11px] font-medium text-foreground">
            {useApiMode ? "Données opérationnelles · API" : "Données simulées · Mode prototype"}
          </div>

          {configMode && isCreating && (
            <div className="pointer-events-none absolute bottom-4 left-1/2 z-10 max-w-md -translate-x-1/2 rounded-md border border-border bg-surface/95 px-3 py-2 text-center text-[11px] shadow-sm">
              <span className="font-medium text-foreground">
                {configTab === "routes" ? "Tracé de route" : "Dessin de zone"}
              </span>
              <span className="text-muted">
                {configTab === "routes"
                  ? ` — cliquez sur la carte pour ajouter les sommets de la route. ${draftPoints.length} point${draftPoints.length !== 1 ? "s" : ""} défini${draftPoints.length !== 1 ? "s" : ""} (minimum 2). Enregistrez quand le tracé est complet.`
                  : ` — cliquez pour placer les sommets (${draftPoints.length}/3 min.) · Backspace pour annuler le dernier point`}
              </span>
            </div>
          )}

          {configMode && !isCreating && (
            <div className="absolute right-3 top-12 z-10 rounded-md border border-border bg-surface/95 px-2.5 py-1.5 text-[11px] text-muted shadow-sm">
              {activeTool === "delete"
                ? configTab === "routes"
                  ? "Cliquez une route sur la carte pour la supprimer"
                  : "Cliquez une zone sur la carte pour la supprimer"
                : activeTool === "vertex"
                  ? configTab === "routes"
                    ? "Glissez les points du tracé, puis enregistrez"
                    : "Glissez les sommets pour ajuster la forme"
                  : configTab === "routes"
                    ? "Sélectionnez une route ou tracez-en une nouvelle"
                    : "Sélectionnez une zone ou appuyez + pour en créer une"}
            </div>
          )}
        </div>

        <div className="w-[280px] shrink-0 border-l border-border">
          {configMode && configTab === "zones" ? (
            <ZonePropertiesPanel
              draft={draft}
              onChange={(patch) => setDraft((d) => (d ? { ...d, ...patch } : d))}
              onSave={handleSaveDraft}
              onCancel={handleCancelDraft}
              onDelete={handleDeleteZone}
              onUndoPoint={undoLastPoint}
              isCreating={isCreating}
              isEditingVertices={isEditingVertices}
              canFinishDraft={draftPoints.length >= 3}
              pointCount={draftPoints.length}
            />
          ) : configMode ? (
            <RoadPropertiesPanel
              draft={roadDraft}
              zones={zones}
              onChange={(patch) => setRoadDraft((d) => (d ? { ...d, ...patch } : d))}
              onSave={() => void handleSaveRoad()}
              onCancel={handleCancelDraft}
              onDelete={handleDeleteRoad}
              onUndoPoint={undoLastPoint}
              onEditTrace={startRoadTraceEdit}
              onAddVertex={() =>
                setRoadEditingVertices((pts) => (pts ? insertMidpointOnLongestSegment(pts) : pts))
              }
              onRemoveVertex={() =>
                setRoadEditingVertices((pts) => (pts ? removeLastVertex(pts) : pts))
              }
              isCreating={isCreating}
              isEditingTrace={isEditingRoadVertices}
              canFinishDraft={canSaveCurrentRoad}
              pointCount={roadPointCount}
            />
          ) : (
            <div className="flex h-full flex-col">
              <div className="shrink-0 border-b border-border px-3 py-2.5">
                <h3 className="text-[11px] font-semibold uppercase tracking-wide text-foreground/80">
                  Info rapide
                </h3>
              </div>
              <div className="min-h-0 flex-1 overflow-y-auto p-3">
                {selectedEquipment ? (
                  <EquipmentQuickInfo
                    equipmentId={selectedEquipment.id}
                    inference={pipContext?.inference ?? null}
                    showRecentPath={showRecentPath}
                    onToggleRecentPath={() => setShowRecentPath((v) => !v)}
                    onOpenDetail={() => openEquipmentDrawer(selectedEquipment.id)}
                  />
                ) : selectedRoad ? (
                  <RoadQuickInfo
                    road={selectedRoad}
                    zones={zones}
                    onConfigure={() => {
                      enterConfigMode("routes")
                      selectRoadForEdit(selectedRoad.id)
                    }}
                  />
                ) : selectedZone ? (
                  <ZoneQuickInfo
                    zone={selectedZone}
                    occupancy={equipment.filter((e) => e.zoneId === selectedZone.id).length}
                    equipmentInside={equipment.filter((e) => e.zoneId === selectedZone.id)}
                    avgWait={useApiMode ? null : avgWaitInZone(equipment, selectedZone.id)}
                    onEdit={() => {
                      enterConfigMode("zones")
                      selectZoneForEdit(selectedZone.id)
                    }}
                  />
                ) : (
                  <p className="text-xs text-muted">
                    Sélectionnez un engin, une zone ou une piste sur la carte pour afficher le détail.
                  </p>
                )}
              </div>
              <div className="shrink-0 border-t border-border px-3 py-2">
                <StatusLegend compact />
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function EquipmentQuickInfo({
  equipmentId,
  inference,
  showRecentPath,
  onToggleRecentPath,
  onOpenDetail,
}: {
  equipmentId: string
  inference: string | null
  showRecentPath: boolean
  onToggleRecentPath: () => void
  onOpenDetail: () => void
}) {
  const equipment = useOpsStore((s) => s.equipment)
  const operators = useOpsStore((s) => s.operators)
  const zones = useOpsStore((s) => s.zones)
  const eq = equipment.find((e) => e.id === equipmentId)
  if (!eq) return null
  const operator = operators.find((o) => o.id === eq.operatorId)
  const zone = zones.find((z) => z.id === eq.zoneId)
  const cfg = STATE_CONFIG[eq.state]

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-2">
        <div className={cn("flex size-10 items-center justify-center rounded-md p-0.5", cfg.bg)}>
          <EquipmentTypeIcon type={eq.type} className="size-9" title={eq.code} />
        </div>
        <div className="min-w-0 flex-1">
          <p className="font-mono text-sm font-semibold text-foreground">{eq.code}</p>
          <p className="truncate text-[11px] text-muted">{eq.model}</p>
        </div>
      </div>
      <Badge className={cn(cfg.bg, cfg.color, "w-fit border-transparent")}>{cfg.label}</Badge>
      <div className="grid grid-cols-2 gap-2 text-[11px]">
        <QuickStat label="Vitesse" value={eq.speedKmh != null ? `${eq.speedKmh.toFixed(0)} km/h` : "—"} />
        <QuickStat label="Gasoil" value={eq.fuelPct != null ? `${eq.fuelPct.toFixed(0)}%` : "—"} />
      </div>
      <div className="flex items-center gap-1.5 text-[11px] text-muted">
        <User className="size-3.5 text-muted-2" />
        {operator ? operator.name : useApiMode ? "Opérateur non renseigné" : "Non affecté"}
      </div>
      <div className="flex items-center gap-1.5 text-[11px] text-muted">
        <MapPin className="size-3.5 text-muted-2" />
        {zone ? zone.name : "Zone inconnue"}
      </div>
      {inference && (
        <p className="rounded-md border border-border bg-surface-2/60 px-2.5 py-2 text-[11px] leading-relaxed text-muted">
          {inference}
        </p>
      )}
      <Button size="sm" onClick={onOpenDetail}>
        Ouvrir l&apos;inspecteur
      </Button>
      <Button size="sm" disabled={useApiMode} variant={showRecentPath ? "default" : "outline"} onClick={onToggleRecentPath}>
        {useApiMode ? "Historique GPS non disponible" : showRecentPath ? "Masquer le trajet récent" : "Afficher le trajet récent"}
      </Button>
      <AiSlot insight={inspecteurInsight(eq.id, eq.code)} label="Pourquoi" />
    </div>
  )
}

function ZoneQuickInfo({
  zone,
  occupancy,
  equipmentInside,
  avgWait,
  onEdit,
}: {
  zone: Zone
  occupancy: number
  equipmentInside: { id: string; code: string }[]
  avgWait: number | null
  onEdit: () => void
}) {
  const ratio = zone.capacity != null && zone.capacity > 0 ? occupancy / zone.capacity : 0
  const condition = useApiMode || zone.capacity == null ? "Non évalué" : zoneConditionLabel(occupancy, zone.capacity)
  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-2">
        <span className="size-3 shrink-0 rounded-sm" style={{ backgroundColor: zone.color }} />
        <div>
          <p className="text-sm font-semibold text-foreground">{zone.name}</p>
          <p className="text-[11px] text-muted-2">{ZONE_TYPE_LABEL[zone.type]}</p>
        </div>
      </div>
      <p className="text-xs leading-relaxed text-muted">{zone.description}</p>
      <div className="grid grid-cols-2 gap-2">
        <QuickStat label="Présents" value={`${occupancy}`} />
        <QuickStat label="Capacité" value={zone.capacity != null ? `${zone.capacity}` : "—"} />
        <QuickStat label="Attente moy." value={avgWait == null ? "Indisponible" : `${avgWait.toFixed(0)} min`} />
        <QuickStat label="État" value={condition} />
      </div>
      {condition === "congestion" && (
        <p className="flex items-center gap-1.5 text-[11px] text-danger">
          <AlertTriangle className="size-3.5" />
          Congestion — file au-delà de la capacité
        </p>
      )}
      {equipmentInside.length > 0 && (
        <div>
          <p className="mb-1 text-[10px] font-semibold uppercase text-muted-2">Engins dans la zone</p>
          <div className="flex flex-wrap gap-1">
            {equipmentInside.slice(0, 12).map((e) => (
              <Badge key={e.id} variant="outline" className="font-mono text-[10px]">
                {e.code}
              </Badge>
            ))}
          </div>
        </div>
      )}
      {zone.capacity != null && zone.capacity > 0 && (
        <div className="flex flex-col gap-1">
          <div className="flex items-center justify-between text-[11px]">
            <span className="text-muted">Occupation</span>
            <span className="tabular-nums font-medium text-foreground/90">
              {occupancy}/{zone.capacity}
            </span>
          </div>
          <div className="h-1.5 overflow-hidden rounded-md bg-surface-3">
            <div
              className={cn(
                "h-full rounded-md",
                useApiMode ? "bg-accent" : ratio >= 1 ? "bg-danger" : ratio >= 0.7 ? "bg-warning" : "bg-accent"
              )}
              style={{ width: `${Math.min(100, ratio * 100)}%` }}
            />
          </div>
        </div>
      )}
      <Button size="sm" variant="outline" onClick={onEdit}>
        <Pencil className="size-3.5" />
        Configurer la carte
      </Button>
    </div>
  )
}

function RoadQuickInfo({
  road,
  zones,
  onConfigure,
}: {
  road: RoutePath
  zones: Zone[]
  onConfigure: () => void
}) {
  const from = zones.find((z) => z.id === road.fromZoneId)
  const to = zones.find((z) => z.id === road.toZoneId)
  const status = roadStatus(road)
  return (
    <div className="flex flex-col gap-3">
      <div>
        <p className="font-mono text-sm font-semibold text-foreground">{road.id}</p>
        {road.name && road.name !== road.id && (
          <p className="text-[11px] text-muted">{road.name}</p>
        )}
      </div>
      <QuickStat label="Statut" value={ROAD_STATUS_LABEL[status]} />
      {from && <QuickStat label="De" value={from.name} />}
      {to && <QuickStat label="Vers" value={to.name} />}
      {road.distanceKm != null && <QuickStat label="Distance" value={`${road.distanceKm} km`} />}
      {road.speedLimitKmh != null && (
        <QuickStat label="Vitesse maximale" value={`${road.speedLimitKmh} km/h`} />
      )}
      {road.description ? <p className="text-xs leading-relaxed text-muted">{road.description}</p> : null}
      {status !== "OPEN" && road.statusReason && road.statusReason in ROAD_STATUS_REASON_LABEL && (
        <p className="text-xs text-muted">
          Motif : {ROAD_STATUS_REASON_LABEL[road.statusReason]}
          {road.statusNote ? ` — ${road.statusNote}` : ""}
        </p>
      )}
      <Button size="sm" variant="outline" onClick={onConfigure}>
        <Pencil className="size-3.5" />
        Configurer la carte
      </Button>
    </div>
  )
}

function QuickStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-border bg-surface-2/50 px-2 py-1.5">
      <p className="text-[9px] uppercase tracking-wider text-muted-2">{label}</p>
      <p className="text-xs font-semibold tabular-nums capitalize text-foreground">{value}</p>
    </div>
  )
}
