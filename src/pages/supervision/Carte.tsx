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
import type { EquipmentType, FilmStateGroup, Vec2, Zone } from "@/lib/mock/types"
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
import { DEFAULT_BASEMAP, ZONES_STORAGE_KEY } from "@/features/map/map.constants"
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
import { useApiMode, createZone, deleteZone, patchZone } from "@/lib/api/client"
import { withoutMatchingError } from "@/lib/store/apiSync"

const ALL_TYPES = Object.keys(EQUIPMENT_TYPE_LABEL) as EquipmentType[]
const ALL_GROUPS = Object.keys(FILM_STATE_GROUP_LABEL) as FilmStateGroup[]

function emptyDraft(): ZoneDraft {
  return { name: "Nouvelle zone", type: "chargement", color: "#2F6FED", description: "", capacity: 2 }
}

function MapFlyTo({
  equipmentId,
  equipment,
}: {
  equipmentId: string | null
  equipment: ReturnType<typeof useSiteScopedEquipment>
}) {
  const { map, ready } = useMineMap()
  useEffect(() => {
    if (!map || !ready || !equipmentId) return
    const eq = equipment.find((e) => e.id === equipmentId)
    if (!eq) return
    if (!eq?.position) return
    const [lng, lat] = workspaceToLngLat(eq.position)
    map.easeTo({ center: [lng, lat], zoom: Math.max(map.getZoom(), 15.5), duration: 600 })
  }, [map, ready, equipmentId]) // eslint-disable-line react-hooks/exhaustive-deps -- fly once on selection
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

function FitOnReady({ equipment }: { equipment: ReturnType<typeof useSiteScopedEquipment> }) {
  const { map, ready } = useMineMap()
  const didFit = useRef(false)
  useEffect(() => {
    if (!map || !ready || didFit.current) return
    const bounds = fitBoundsFromEquipment(equipment)
    if (!bounds) return
    map.fitBounds(bounds, { padding: 64, duration: 0, maxZoom: 15.5 })
    didFit.current = true
  }, [map, ready, equipment])
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

export default function Carte() {
  const equipment = useSiteScopedEquipment()
  const zones = useSiteScopedZones()
  const routes = useSiteScopedRoutes()
  const alerts = useOpsStore((s) => s.alerts)
  const selectedSiteId = useOpsStore((s) => s.selectedSiteId)
  const selectedShiftId = useOpsStore((s) => s.selectedShiftId)
  const setZones = useOpsStore((s) => s.setZones)
  const openEquipmentDrawer = useUiStore((s) => s.openEquipmentDrawer)

  const [basemap, setBasemap] = useState<BasemapId>(DEFAULT_BASEMAP)
  const [typeFilter, setTypeFilter] = useState<Set<EquipmentType>>(new Set(ALL_TYPES))
  const [groupFilter, setGroupFilter] = useState<Set<FilmStateGroup>>(new Set(ALL_GROUPS))
  const [zoneFilter, setZoneFilter] = useState<string>("all")
  const [search, setSearch] = useState("")
  const [showZonesLayer, setShowZonesLayer] = useState(true)
  const [showRoadsLayer, setShowRoadsLayer] = useState(true)
  const [showEquipmentLayer, setShowEquipmentLayer] = useState(true)
  const [onlyActiveEvents, setOnlyActiveEvents] = useState(false)
  const [showRecentPath, setShowRecentPath] = useState(false)

  const [selectedEquipmentId, setSelectedEquipmentId] = useState<string | null>(null)
  const [selectedZoneId, setSelectedZoneId] = useState<string | null>(null)

  const [editMode, setEditMode] = useState(false)
  const [activeTool, setActiveTool] = useState<MapTool>("select")
  const [draftPoints, setDraftPoints] = useState<Vec2[]>([])
  const [draftLngLat, setDraftLngLat] = useState<[number, number][]>([])
  const [draft, setDraft] = useState<ZoneDraft | null>(null)
  const [isCreating, setIsCreating] = useState(false)
  const [editingVertices, setEditingVertices] = useState<Vec2[] | null>(null)
  const [focusZoneId, setFocusZoneId] = useState<string | null>(null)

  useMapLiveSimulation(!editMode && !useApiMode)

  // Prototype zone persistence (mock mode only)
  useEffect(() => {
    if (useApiMode) return
    try {
      const raw = localStorage.getItem(ZONES_STORAGE_KEY)
      if (!raw) return
      const saved = JSON.parse(raw) as Zone[]
      if (!Array.isArray(saved) || saved.length === 0) return
      setZones((current) => {
        const byId = new Map(current.map((z) => [z.id, z]))
        for (const z of saved) {
          if (z.siteId === selectedSiteId) byId.set(z.id, z)
        }
        return Array.from(byId.values())
      })
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

  const equipmentGeo = useMemo(
    () => equipmentToGeoJSON(showEquipmentLayer ? filteredEquipment : [], zones, selectedEquipmentId),
    [filteredEquipment, zones, selectedEquipmentId, showEquipmentLayer]
  )
  const zonesGeo = useMemo(
    () => zonesToGeoJSON(zones, equipment, selectedZoneId),
    [zones, equipment, selectedZoneId]
  )
  const roadsGeo = useMemo(() => routesToGeoJSON(routes, zones), [routes, zones])
  const draftGeo = useMemo(() => draftLngLatToGeoJSON(draftLngLat), [draftLngLat])
  const recentGeo = useMemo(() => {
    if (!showRecentPath || !selectedEquipment) {
      return { type: "FeatureCollection" as const, features: [] }
    }
    return recentPathToGeoJSON(buildRecentTrail(selectedEquipment, routes))
  }, [showRecentPath, selectedEquipment, routes])

  const pipContext = useMemo(() => {
    if (!selectedEquipment) return null
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

  function enterEditMode() {
    setEditMode(true)
    setActiveTool("select")
    setSelectedEquipmentId(null)
    setShowRecentPath(false)
    setDraft(null)
    setIsCreating(false)
    setDraftPoints([])
    setDraftLngLat([])
    setEditingVertices(null)
  }

  function exitEditMode() {
    setEditMode(false)
    setSelectedZoneId(null)
    setDraft(null)
    setIsCreating(false)
    setDraftPoints([])
    setDraftLngLat([])
    setEditingVertices(null)
    setActiveTool("select")
  }

  function selectZoneForEdit(id: string) {
    const z = zones.find((zz) => zz.id === id)
    if (!z) return
    setSelectedZoneId(id)
    setIsCreating(false)
    setDraftPoints([])
    setDraftLngLat([])
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

  function startNewZone() {
    setSelectedZoneId(null)
    setIsCreating(true)
    setActiveTool("polygon")
    setDraftPoints([])
    setDraftLngLat([])
    setEditingVertices(null)
    setDraft(emptyDraft())
  }

  function handleAddZone() {
    if (!editMode) {
      setEditMode(true)
      setSelectedEquipmentId(null)
      setShowRecentPath(false)
    }
    startNewZone()
  }

  function handleToolChange(tool: MapTool) {
    setActiveTool(tool)
    if (tool === "polygon") {
      startNewZone()
      return
    }
    setIsCreating(false)
    setDraftPoints([])
    setDraftLngLat([])
    if (tool === "vertex") {
      if (selectedZoneId) {
        const z = zones.find((zz) => zz.id === selectedZoneId)
        if (z) setEditingVertices([...z.points])
      } else {
        setEditingVertices(null)
      }
      return
    }
    setEditingVertices(null)
  }

  const handleCanvasClick = useCallback(
    (lngLat: [number, number]) => {
      if (isCreating && activeTool === "polygon") {
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
    if (editMode) {
      if (activeTool === "delete") {
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
      setSelectedZoneId(id)
    }
  }

  function handleEquipmentClick(id: string) {
    if (editMode) return
    setSelectedZoneId(null)
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
              capacity: draft.capacity,
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
              capacity: draft.capacity,
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

  function handleCancelDraft() {
    setIsCreating(false)
    setDraftPoints([])
    setDraftLngLat([])
    setSelectedZoneId(null)
    setDraft(null)
    setEditingVertices(null)
    setActiveTool("select")
  }

  function handleDeleteZone() {
    if (!selectedZoneId) return
    void removeZone(selectedZoneId).then(() => {
      setSelectedZoneId(null)
      setDraft(null)
      setEditingVertices(null)
    })
  }

  function handleMapReady(map: MapLibreMap) {
    const bounds = fitBoundsFromEquipment(filteredEquipment)
    if (bounds) map.fitBounds(bounds, { padding: 64, duration: 0, maxZoom: 15.5 })
  }

  useEffect(() => {
    if (!editMode) return
    function onKey(e: KeyboardEvent) {
      const target = e.target as HTMLElement
      if (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.tagName === "SELECT")
        return
      if (e.key === "Backspace" && isCreating && draftPoints.length > 0) {
        e.preventDefault()
        undoLastPoint()
      } else if (e.key === "Escape") {
        if (isCreating || draft) handleCancelDraft()
        else exitEditMode()
      } else if (e.key === "Enter" && isCreating && draftPoints.length >= 3 && draft) {
        handleSaveDraft()
      }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps -- keyboard shortcuts for edit session
  }, [editMode, isCreating, draftPoints.length, draft])

  const isEditingVertices = activeTool === "vertex" && editingVertices !== null && !isCreating

  return (
    <div className="flex h-full flex-col">
      {editMode && <ZoneEditorToolbar activeTool={activeTool} onToolChange={handleToolChange} />}
      <div className="flex min-h-0 flex-1">
        {editMode ? (
          <div className="w-[220px] shrink-0 border-r border-border">
            <ZoneListPanel
              zones={zones}
              selectedZoneId={selectedZoneId}
              onSelectZone={selectZoneForEdit}
              onNewZone={startNewZone}
              creating={isCreating}
            />
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
            className={cn("h-full w-full", editMode && isCreating && activeTool === "polygon" && "mp-map-drawing")}
          >
            <HaulRoadsLayer data={roadsGeo} visible={showRoadsLayer && !editMode} />
            <OperationalZonesLayer
              data={zonesGeo}
              visible={showZonesLayer}
              interactive={!isCreating}
              onZoneClick={handleZoneClick}
            />
            <EquipmentLayer
              data={equipmentGeo}
              visible={showEquipmentLayer && !editMode}
              interactive={!editMode}
              onEquipmentClick={handleEquipmentClick}
            />
            <RecentPathLayer data={recentGeo} visible={showRecentPath && !editMode} />
            <ZoneDraftLayer
              data={draftGeo}
              enabled={editMode && isCreating && activeTool === "polygon"}
              color={draft?.color}
              onMapClick={handleCanvasClick}
              onDoubleClickFinish={() => {
                /* contour closed visually at ≥3 pts — user saves from panel */
              }}
              pointCount={draftPoints.length}
            />
            <MapInteractionLock
              mode={editMode && isCreating && activeTool === "polygon" ? "draw" : "none"}
            />
            <ZoneVertexLayer
              points={editingVertices ?? []}
              enabled={editMode && isEditingVertices}
              color={draft?.color}
              onPointsChange={setEditingVertices}
            />
            <MapFlyTo equipmentId={selectedEquipmentId} equipment={equipment} />
            <FlyToZone
              zone={
                focusZoneId ? (zones.find((z) => z.id === focusZoneId) ?? null) : null
              }
            />
            <FitOnReady equipment={filteredEquipment} />
            <MapControls
              basemap={basemap}
              onBasemapChange={setBasemap}
              editMode={editMode}
              onToggleEdit={editMode ? exitEditMode : enterEditMode}
              onAddZone={handleAddZone}
              isDrawing={isCreating}
              fitEquipment={filteredEquipment}
            />
            {!editMode && <MapLegend />}
          </MineMap>

          <div className="pointer-events-none absolute right-3 top-3 z-10 rounded-md border border-warning/30 bg-warning/15 px-2.5 py-1 text-[11px] font-medium text-foreground">
            Données simulées · Mode prototype
          </div>

          {editMode && isCreating && (
            <div className="pointer-events-none absolute bottom-4 left-1/2 z-10 max-w-md -translate-x-1/2 rounded-md border border-border bg-surface/95 px-3 py-2 text-center text-[11px] shadow-sm">
              <span className="font-medium text-foreground">Dessin de zone</span>
              <span className="text-muted">
                {" "}
                — cliquez pour placer les sommets ({draftPoints.length}/3 min.) · double-clic pour
                terminer · Backspace pour annuler le dernier point
              </span>
            </div>
          )}

          {editMode && !isCreating && (
            <div className="absolute right-3 top-12 z-10 rounded-md border border-border bg-surface/95 px-2.5 py-1.5 text-[11px] text-muted shadow-sm">
              {activeTool === "delete"
                ? "Cliquez une zone sur la carte pour la supprimer"
                : activeTool === "vertex"
                  ? "Glissez les sommets pour ajuster la forme"
                  : "Sélectionnez une zone ou appuyez + pour en créer une"}
            </div>
          )}
        </div>

        <div className="w-[280px] shrink-0 border-l border-border">
          {editMode ? (
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
                ) : selectedZone ? (
                  <ZoneQuickInfo
                    zone={selectedZone}
                    occupancy={equipment.filter((e) => e.zoneId === selectedZone.id).length}
                    equipmentInside={equipment.filter((e) => e.zoneId === selectedZone.id)}
                    avgWait={avgWaitInZone(equipment, selectedZone.id)}
                    onEdit={() => {
                      enterEditMode()
                      selectZoneForEdit(selectedZone.id)
                    }}
                  />
                ) : (
                  <p className="text-xs text-muted">
                    Sélectionnez un engin ou une zone sur la carte pour afficher le détail.
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
        {operator ? operator.name : "Non affecté"}
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
      <Button size="sm" variant={showRecentPath ? "default" : "outline"} onClick={onToggleRecentPath}>
        {showRecentPath ? "Masquer le trajet récent" : "Afficher le trajet récent"}
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
  avgWait: number
  onEdit: () => void
}) {
  const ratio = zone.capacity > 0 ? occupancy / zone.capacity : 0
  const condition = zoneConditionLabel(occupancy, zone.capacity)
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
        <QuickStat label="Capacité" value={zone.capacity > 0 ? `${zone.capacity}` : "—"} />
        <QuickStat label="Attente moy." value={`${avgWait.toFixed(0)} min`} />
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
      {zone.capacity > 0 && (
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
                ratio >= 1 ? "bg-danger" : ratio >= 0.7 ? "bg-warning" : "bg-accent"
              )}
              style={{ width: `${Math.min(100, ratio * 100)}%` }}
            />
          </div>
        </div>
      )}
      <Button size="sm" variant="outline" onClick={onEdit}>
        <Pencil className="size-3.5" />
        Modifier les zones
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
