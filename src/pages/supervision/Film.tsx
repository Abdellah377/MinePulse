import { useEffect, useMemo, useRef, useState, type ReactNode } from "react"
import { Search } from "lucide-react"

import { useOpsStore, useSiteScopedEquipment } from "@/lib/store/useOpsStore"
import { useUiStore } from "@/lib/store/useUiStore"
import {
  EQUIPMENT_TYPE_LABEL,
  FILM_STATE_GROUP,
  FILM_STATE_GROUP_LABEL,
} from "@/lib/mock/types"
import type { EquipmentType, FilmStateGroup, TimelineSegment } from "@/lib/mock/types"
import { FILM_GROUP_CONFIG } from "@/lib/status"
import { formatElapsedHms, formatShortTime, formatTimeHms } from "@/lib/format"
import { cn } from "@/lib/utils"
import { shiftWindowBounds } from "@/lib/ops/shiftWindow"
import { useApiMode } from "@/lib/api/client"
import { sortEquipmentByCode } from "@/lib/equipmentOrder"
import { filmSegmentInsight } from "@/lib/ai/placeholders"
import { AiSlot } from "@/components/ai/AiSlot"
import { StatusLegend } from "@/components/shared/StatusLegend"
import { PeriodFilters } from "@/components/shared/PeriodFilters"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { MiniTimelineStrip } from "@/components/equipment/MiniTimelineStrip"

const WINDOW_MIN = 720
const MIN_TIMELINE_WIDTH_PX = 480
const LABEL_WIDTH = 72
const ROW_HEIGHT = 36
const GROUP_HEADER_HEIGHT = 26
const RULER_HEIGHT = 28
const PARAMS_WIDTH = 200
const SEGMENT_INSET = 8

const ALL_GROUPS = Object.keys(FILM_STATE_GROUP_LABEL) as FilmStateGroup[]
const ALL_TYPES = Object.keys(EQUIPMENT_TYPE_LABEL) as EquipmentType[]

type Selection = { type: "segment"; equipmentId: string; segment: TimelineSegment } | { type: "row"; equipmentId: string } | null

export default function Film({ tab }: Partial<import("@/components/workspace/WorkspaceHost").WorkspacePanelProps> = {}) {
  const equipment = useSiteScopedEquipment()
  const timelineSegments = useOpsStore((s) => s.timelineSegments)
  const shifts = useOpsStore((s) => s.shifts)
  const selectedShiftId = useOpsStore((s) => s.selectedShiftId)
  const simNowIso = useOpsStore((s) => s.simNowIso)
  const openEquipmentDrawer = useUiStore((s) => s.openEquipmentDrawer)

  const shift = shifts.find((s) => s.id === selectedShiftId) ?? (useApiMode ? undefined : shifts[0])
  const { startMs: shiftStartRef, nowMs: now } = shiftWindowBounds(simNowIso, shift)

  const [typeFilter, setTypeFilter] = useState<"all" | EquipmentType>("all")
  const [stateFilter, setStateFilter] = useState<Set<FilmStateGroup>>(new Set(ALL_GROUPS))
  const [search, setSearch] = useState("")
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({ auxiliaires: true })
  const [emphasize, setEmphasize] = useState(false)
  const [arretsSansCause, setArretsSansCause] = useState(false)
  const [selection, setSelection] = useState<Selection>(null)
  useEffect(() => {
    if (tab?.context.equipmentId) setSelection({ type: "row", equipmentId: tab.context.equipmentId })
  }, [tab?.context.equipmentId])
  const [timelineWidthPx, setTimelineWidthPx] = useState(MIN_TIMELINE_WIDTH_PX)

  const searchRef = useRef<HTMLInputElement>(null)
  const labelScrollRef = useRef<HTMLDivElement>(null)
  const timelineScrollRef = useRef<HTMLDivElement>(null)
  const syncing = useRef(false)

  const windowMs = WINDOW_MIN * 60_000
  const rangeEnd = useApiMode && shift?.windowEnd ? Math.min(now, Date.parse(shift.windowEnd)) : now
  const rangeStart = Math.max(shiftStartRef, rangeEnd - windowMs)
  const totalWidthPx = timelineWidthPx

  useEffect(() => {
    const el = timelineScrollRef.current
    if (!el) return
    const updateWidth = () => {
      const w = el.clientWidth
      if (w > 0) setTimelineWidthPx(Math.max(MIN_TIMELINE_WIDTH_PX, Math.floor(w)))
    }
    updateWidth()
    const ro = new ResizeObserver(updateWidth)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  useEffect(() => {
    function handler(e: KeyboardEvent) {
      const target = e.target as HTMLElement
      const typing = target.tagName === "INPUT" || target.tagName === "TEXTAREA"
      if (e.key === "/" && !typing) {
        e.preventDefault()
        searchRef.current?.focus()
        return
      }
      if (typing) return
      if (e.key === "Escape") {
        setSelection(null)
        searchRef.current?.blur()
      } else if (e.key === "Enter" && selection) {
        openEquipmentDrawer(selection.equipmentId)
      } else if ((e.key === "j" || e.key === "k") && selection?.type === "row") {
        // handled by row list below via visibleRowIds
      }
    }
    window.addEventListener("keydown", handler)
    return () => window.removeEventListener("keydown", handler)
  }, [selection, openEquipmentDrawer])

  const camions = useMemo(
    () =>
      sortEquipmentByCode(
        equipment
          .filter((e) => e.type === "haul_truck")
          .filter(() => typeFilter === "all" || typeFilter === "haul_truck")
          .filter((e) => search === "" || e.code.toLowerCase().includes(search.toLowerCase()))
          .filter((e) => !arretsSansCause || e.state === "arret_indetermine")
      ),
    [equipment, typeFilter, search, arretsSansCause]
  )
  const pelles = useMemo(
    () =>
      sortEquipmentByCode(
        equipment
          .filter((e) => e.type === "excavator" || e.type === "loader")
          .filter((e) => typeFilter === "all" || typeFilter === e.type)
          .filter((e) => search === "" || e.code.toLowerCase().includes(search.toLowerCase()))
          .filter((e) => !arretsSansCause || e.state === "arret_indetermine")
      ),
    [equipment, typeFilter, search, arretsSansCause]
  )
  const auxiliaires = useMemo(
    () =>
      sortEquipmentByCode(
        equipment
          .filter((e) => e.type !== "haul_truck" && e.type !== "excavator" && e.type !== "loader")
          .filter((e) => typeFilter === "all" || typeFilter === e.type)
          .filter((e) => search === "" || e.code.toLowerCase().includes(search.toLowerCase()))
          .filter((e) => !arretsSansCause || e.state === "arret_indetermine")
      ),
    [equipment, typeFilter, search, arretsSansCause]
  )

  const visibleRowIds = useMemo(() => {
    const ids: string[] = []
    ids.push(...camions.map((e) => e.id))
    if (!collapsed.pelles) ids.push(...pelles.map((e) => e.id))
    if (!collapsed.auxiliaires) ids.push(...auxiliaires.map((e) => e.id))
    return ids
  }, [camions, pelles, auxiliaires, collapsed])

  useEffect(() => {
    function handler(e: KeyboardEvent) {
      if (e.key !== "j" && e.key !== "k") return
      const target = e.target as HTMLElement
      if (target.tagName === "INPUT" || target.tagName === "TEXTAREA") return
      if (visibleRowIds.length === 0) return
      const currentId = selection?.equipmentId ?? null
      const idx = currentId ? visibleRowIds.indexOf(currentId) : -1
      const nextIdx = e.key === "j" ? Math.min(visibleRowIds.length - 1, idx + 1) : Math.max(0, idx - 1)
      setSelection({ type: "row", equipmentId: visibleRowIds[nextIdx] })
    }
    window.addEventListener("keydown", handler)
    return () => window.removeEventListener("keydown", handler)
  }, [visibleRowIds, selection])

  const segmentsByEquipment = useMemo(() => {
    const map = new Map<string, TimelineSegment[]>()
    for (const seg of timelineSegments) {
      if (seg.end < rangeStart || seg.start > rangeEnd) continue
      const arr = map.get(seg.equipmentId) ?? []
      arr.push(seg)
      map.set(seg.equipmentId, arr)
    }
    return map
  }, [timelineSegments, rangeStart, rangeEnd])

  const allSegmentsByEquipment = useMemo(() => {
    const map = new Map<string, TimelineSegment[]>()
    for (const seg of timelineSegments) {
      const arr = map.get(seg.equipmentId) ?? []
      arr.push(seg)
      map.set(seg.equipmentId, arr)
    }
    return map
  }, [timelineSegments])

  function toggleEmphasize() {
    if (emphasize) {
      setStateFilter(new Set(ALL_GROUPS))
      setEmphasize(false)
    } else {
      setStateFilter(new Set(["attente", "arret"] as FilmStateGroup[]))
      setEmphasize(true)
    }
  }

  function toggleStateChip(g: FilmStateGroup) {
    setStateFilter((prev) => {
      const next = new Set(prev)
      if (next.has(g)) next.delete(g)
      else next.add(g)
      return next
    })
    setEmphasize(false)
  }

  function syncFromTimeline() {
    if (syncing.current) return
    syncing.current = true
    if (labelScrollRef.current && timelineScrollRef.current) {
      labelScrollRef.current.scrollTop = timelineScrollRef.current.scrollTop
    }
    syncing.current = false
  }

  function syncFromLabel() {
    if (syncing.current) return
    syncing.current = true
    if (labelScrollRef.current && timelineScrollRef.current) {
      timelineScrollRef.current.scrollTop = labelScrollRef.current.scrollTop
    }
    syncing.current = false
  }

  const ticks = useMemo(() => {
    const stepMin = 60
    const stepMs = stepMin * 60_000
    const first = Math.ceil(rangeStart / stepMs) * stepMs
    const arr: number[] = []
    for (let t = first; t <= rangeEnd; t += stepMs) arr.push(t)
    return arr
  }, [rangeStart, rangeEnd])

  const nowLeftPx = ((now - rangeStart) / (rangeEnd - rangeStart)) * totalWidthPx
  const showNowLine = now >= rangeStart && now <= rangeEnd

  const totalAuxWaiting = auxiliaires.reduce((sum, e) => sum + e.waitingMinutesThisShift, 0)

  if (useApiMode && (!Number.isFinite(rangeStart) || !Number.isFinite(rangeEnd) || rangeEnd <= rangeStart)) {
    return <div className="p-4 text-sm text-muted"><PeriodFilters />Fenêtre opérationnelle indisponible ou poste non commencé.</div>
  }

  return (
    <div className="flex h-full gap-3 overflow-hidden p-3 pt-1">
      <aside
        className="flex shrink-0 flex-col overflow-hidden rounded-2xl border border-border/80 bg-surface shadow-soft"
        style={{ width: PARAMS_WIDTH }}
      >
        <div className="sticky top-0 z-20 flex h-10 items-center bg-surface px-4 text-[11px] font-semibold uppercase tracking-wide text-foreground/80">
          Paramètres
        </div>
        <div className="flex flex-1 flex-col gap-3 overflow-y-auto px-3 pb-3">
          <PeriodFilters className="border-b border-border pb-3" />

          <div>
            <label className="mb-1 block text-[10px] font-semibold uppercase text-muted-2">
              Type d'engin
            </label>
            <Select value={typeFilter} onValueChange={(v) => setTypeFilter(v as "all" | EquipmentType)}>
              <SelectTrigger className="h-7 rounded-xl text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Tous les types</SelectItem>
                {ALL_TYPES.map((t) => (
                  <SelectItem key={t} value={t}>
                    {EQUIPMENT_TYPE_LABEL[t]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div>
            <label className="mb-1 block text-[10px] font-semibold uppercase text-muted-2">
              Recherche
            </label>
            <div className="relative">
              <Search className="pointer-events-none absolute left-2 top-1/2 size-3 -translate-y-1/2 text-muted-2" />
              <Input
                ref={searchRef}
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="ID… ( / )"
                className="h-7 rounded-xl pl-7 text-xs"
              />
            </div>
          </div>

          <div>
            <label className="mb-1 block text-[10px] font-semibold uppercase text-muted-2">
              Groupes
            </label>
            <div className="overflow-hidden rounded-xl border border-border bg-background text-[11px]">
              <label className="flex items-center gap-2 border-b border-border px-3 py-2">
                <input type="checkbox" checked readOnly className="accent-accent" />
                Camions
                <span className="ml-auto text-muted-2">{camions.length}</span>
              </label>
              <label className="flex items-center gap-2 border-b border-border px-3 py-2">
                <input
                  type="checkbox"
                  checked={!collapsed.pelles}
                  onChange={() => setCollapsed((c) => ({ ...c, pelles: !c.pelles }))}
                  className="accent-accent"
                />
                Pelles
                <span className="ml-auto text-muted-2">{pelles.length}</span>
              </label>
              <label className="flex items-center gap-2 px-3 py-2">
                <input
                  type="checkbox"
                  checked={!collapsed.auxiliaires}
                  onChange={() => setCollapsed((c) => ({ ...c, auxiliaires: !c.auxiliaires }))}
                  className="accent-accent"
                />
                Auxiliaires
                <span className="ml-auto text-muted-2">{auxiliaires.length}</span>
              </label>
            </div>
          </div>

          <div>
            <label className="mb-1 block text-[10px] font-semibold uppercase text-muted-2">
              États
            </label>
            <div className="flex flex-col gap-0.5">
              {ALL_GROUPS.map((g) => {
                const cfg = FILM_GROUP_CONFIG[g]
                const active = stateFilter.has(g)
                return (
                  <button
                    key={g}
                    type="button"
                    onClick={() => toggleStateChip(g)}
                    className={cn(
                      "flex h-6 items-center gap-1.5 rounded-none border px-1.5 text-left text-[10px] font-medium",
                      active
                        ? "border-border-strong bg-background text-foreground"
                        : "border-transparent text-muted-2"
                    )}
                  >
                    <span className={cn("size-2.5 shrink-0 rounded-none", cfg.dot)} />
                    {cfg.label}
                  </button>
                )
              })}
            </div>
          </div>

          <Button
            variant={emphasize ? "secondary" : "outline"}
            size="sm"
            className={cn("h-7 rounded-xl text-[11px]", emphasize && "text-accent")}
            onClick={toggleEmphasize}
          >
            Attentes / arrêts
          </Button>
          <Button
            variant={arretsSansCause ? "secondary" : "outline"}
            size="sm"
            className={cn("h-7 rounded-xl text-[11px]", arretsSansCause && "text-danger")}
            onClick={() => setArretsSansCause((v) => !v)}
          >
            Arrêts sans cause
          </Button>
        </div>

        <div className="border-t border-border p-2.5">
          <Button
            className="h-8 w-full rounded-xl text-[11px] font-semibold"
            onClick={() => {
              setArretsSansCause(false)
            }}
          >
            Actualiser
          </Button>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col overflow-hidden rounded-2xl border border-border/80 bg-surface shadow-soft">
        <div className="sticky top-0 z-20 flex h-10 shrink-0 items-center gap-2 border-b border-border bg-surface px-3">
          <span className="text-[10px] font-semibold uppercase tracking-wide text-muted-2">
            Film · focus poste
          </span>
        </div>

      <div className="flex min-h-0 flex-1">
        <div className="flex min-h-0 flex-1">
          <div
            ref={labelScrollRef}
            onScroll={syncFromLabel}
            className="shrink-0 overflow-y-auto overflow-x-hidden border-r border-border scrollbar-none"
            style={{ width: LABEL_WIDTH }}
          >
            <div style={{ height: RULER_HEIGHT }} className="sticky top-0 z-10 border-b border-border bg-surface" />

            <GroupBlock title="Camions" count={camions.length} collapsed={false} onToggle={() => {}} locked>
              {camions.map((eq) => (
                <RowLabel
                  key={eq.id}
                  code={eq.code}
                  sub={`${eq.tripsThisShift}`}
                  selected={selection?.equipmentId === eq.id}
                  onClick={() => setSelection({ type: "row", equipmentId: eq.id })}
                  onDoubleClick={() => openEquipmentDrawer(eq.id)}
                />
              ))}
            </GroupBlock>

            <GroupBlock
              title="Pelles"
              count={pelles.length}
              collapsed={!!collapsed.pelles}
              onToggle={() => setCollapsed((c) => ({ ...c, pelles: !c.pelles }))}
            >
              {!collapsed.pelles &&
                pelles.map((eq) => (
                  <RowLabel
                    key={eq.id}
                    code={eq.code}
                    sub={EQUIPMENT_TYPE_LABEL[eq.type].slice(0, 3)}
                    selected={selection?.equipmentId === eq.id}
                    onClick={() => setSelection({ type: "row", equipmentId: eq.id })}
                    onDoubleClick={() => openEquipmentDrawer(eq.id)}
                  />
                ))}
            </GroupBlock>

            <GroupBlock
              title="Aux."
              count={auxiliaires.length}
              collapsed={!!collapsed.auxiliaires}
              onToggle={() => setCollapsed((c) => ({ ...c, auxiliaires: !c.auxiliaires }))}
              aggregateLabel={collapsed.auxiliaires ? `${totalAuxWaiting.toFixed(0)}m` : undefined}
            >
              {!collapsed.auxiliaires &&
                auxiliaires.map((eq) => (
                  <RowLabel
                    key={eq.id}
                    code={eq.code}
                    sub={EQUIPMENT_TYPE_LABEL[eq.type].slice(0, 3)}
                    selected={selection?.equipmentId === eq.id}
                    onClick={() => setSelection({ type: "row", equipmentId: eq.id })}
                    onDoubleClick={() => openEquipmentDrawer(eq.id)}
                  />
                ))}
            </GroupBlock>
          </div>

          <div
            ref={timelineScrollRef}
            onScroll={syncFromTimeline}
            className="relative min-h-0 min-w-0 flex-1 overflow-x-hidden overflow-y-auto"
          >
            <div className="relative" style={{ width: totalWidthPx }}>
              <div
                className="sticky top-0 z-10 border-b border-border bg-surface"
                style={{ height: RULER_HEIGHT }}
              >
                {ticks.map((t) => (
                  <div
                    key={t}
                    className="absolute top-0 flex h-full items-center border-l border-border pl-1 text-[10px] text-muted-2"
                    style={{ left: ((t - rangeStart) / (rangeEnd - rangeStart)) * totalWidthPx }}
                  >
                    {formatShortTime(t)}
                  </div>
                ))}
                {showNowLine && (
                  <div
                    className="absolute top-0 flex h-full -translate-x-full items-center pr-1 text-[9px] font-semibold text-danger"
                    style={{ left: nowLeftPx }}
                  >
                    Maintenant
                  </div>
                )}
              </div>

              {showNowLine && (
                <div
                  className="pointer-events-none absolute top-0 bottom-0 w-px bg-danger/60"
                  style={{ left: nowLeftPx }}
                />
              )}

              <TimelineGroupSpacer height={GROUP_HEADER_HEIGHT} />
              {camions.map((eq) => (
                <TimelineRow
                  key={eq.id}
                  segments={segmentsByEquipment.get(eq.id) ?? []}
                  rangeStart={rangeStart}
                  rangeEnd={rangeEnd}
                  totalWidthPx={totalWidthPx}
                  stateFilter={stateFilter}
                  selected={selection?.equipmentId === eq.id}
                  selectedSegmentId={selection?.type === "segment" ? selection.segment.id : null}
                  onSegmentClick={(seg) => setSelection({ type: "segment", equipmentId: eq.id, segment: seg })}
                  onRowClick={() => setSelection({ type: "row", equipmentId: eq.id })}
                  onDoubleClick={() => openEquipmentDrawer(eq.id)}
                />
              ))}

              <TimelineGroupSpacer height={GROUP_HEADER_HEIGHT} />
              {!collapsed.pelles &&
                pelles.map((eq) => (
                  <TimelineRow
                    key={eq.id}
                    segments={segmentsByEquipment.get(eq.id) ?? []}
                    rangeStart={rangeStart}
                    rangeEnd={rangeEnd}
                    totalWidthPx={totalWidthPx}
                    stateFilter={stateFilter}
                    selected={selection?.equipmentId === eq.id}
                    selectedSegmentId={selection?.type === "segment" ? selection.segment.id : null}
                    onSegmentClick={(seg) => setSelection({ type: "segment", equipmentId: eq.id, segment: seg })}
                    onRowClick={() => setSelection({ type: "row", equipmentId: eq.id })}
                    onDoubleClick={() => openEquipmentDrawer(eq.id)}
                  />
                ))}

              <TimelineGroupSpacer height={GROUP_HEADER_HEIGHT} />
              {!collapsed.auxiliaires &&
                auxiliaires.map((eq) => (
                  <TimelineRow
                    key={eq.id}
                    segments={segmentsByEquipment.get(eq.id) ?? []}
                    rangeStart={rangeStart}
                    rangeEnd={rangeEnd}
                    totalWidthPx={totalWidthPx}
                    stateFilter={stateFilter}
                    selected={selection?.equipmentId === eq.id}
                    selectedSegmentId={selection?.type === "segment" ? selection.segment.id : null}
                    onSegmentClick={(seg) => setSelection({ type: "segment", equipmentId: eq.id, segment: seg })}
                    onRowClick={() => setSelection({ type: "row", equipmentId: eq.id })}
                    onDoubleClick={() => openEquipmentDrawer(eq.id)}
                  />
                ))}
            </div>
          </div>
        </div>

        <div className="w-[300px] shrink-0 overflow-y-auto border-l border-border bg-surface">
          <DetailPanel
            selection={selection}
            equipment={equipment}
            allSegmentsByEquipment={allSegmentsByEquipment}
            rangeStart={shiftStartRef}
            rangeEnd={now}
            onOpenEquipment={(id) => openEquipmentDrawer(id)}
          />
        </div>
      </div>

      <div className="flex shrink-0 flex-wrap items-center gap-3 border-t border-border bg-surface px-3 py-1.5">
        <StatusLegend compact />
      </div>
      </div>
    </div>
  )
}

function GroupBlock({
  title,
  count,
  collapsed,
  onToggle,
  children,
  locked,
  aggregateLabel,
}: {
  title: string
  count: number
  collapsed: boolean
  onToggle: () => void
  children?: ReactNode
  locked?: boolean
  aggregateLabel?: string
}) {
  return (
    <div>
      <button
        onClick={onToggle}
        disabled={locked}
        style={{ height: GROUP_HEADER_HEIGHT }}
        className="flex w-full items-center gap-1.5 border-b border-border bg-surface-2/60 px-2.5 text-left text-[11px] font-semibold text-foreground/80 disabled:cursor-default"
      >
        <span className="text-muted-2">{locked ? "▾" : collapsed ? "▸" : "▾"}</span>
        {title}
        <span className="font-normal text-muted-2">({count})</span>
        {aggregateLabel && <span className="ml-auto text-[10px] font-normal text-warning">{aggregateLabel}</span>}
      </button>
      {children}
    </div>
  )
}

function TimelineGroupSpacer({ height }: { height: number }) {
  return <div style={{ height }} className="border-b border-border bg-surface-2/60" />
}

function RowLabel({
  code,
  sub,
  selected,
  onClick,
  onDoubleClick,
}: {
  code: string
  sub: string
  selected: boolean
  onClick: () => void
  onDoubleClick: () => void
}) {
  return (
    <button
      onClick={onClick}
      onDoubleClick={onDoubleClick}
      style={{ height: ROW_HEIGHT }}
      className={cn(
        "flex w-full items-center gap-2 border-b border-border px-2.5 text-left text-xs transition-colors",
        selected ? "bg-accent-soft text-accent" : "text-foreground/85 hover:bg-surface-2"
      )}
    >
      <span className="font-mono font-medium">{code}</span>
      <span className="ml-auto text-[10px] text-muted-2">{sub}</span>
    </button>
  )
}

function TimelineRow({
  segments,
  rangeStart,
  rangeEnd,
  totalWidthPx,
  stateFilter,
  selected,
  selectedSegmentId,
  onSegmentClick,
  onRowClick,
  onDoubleClick,
}: {
  segments: TimelineSegment[]
  rangeStart: number
  rangeEnd: number
  totalWidthPx: number
  stateFilter: Set<FilmStateGroup>
  selected: boolean
  selectedSegmentId: string | null
  onSegmentClick: (seg: TimelineSegment) => void
  onRowClick: () => void
  onDoubleClick: () => void
}) {
  const windowMs = rangeEnd - rangeStart
  const sortedSegments = useMemo(
    () => [...segments].sort((a, b) => a.start - b.start),
    [segments]
  )
  return (
    <div
      onClick={onRowClick}
      onDoubleClick={onDoubleClick}
      style={{ height: ROW_HEIGHT }}
      className={cn("relative border-b border-border", selected ? "bg-accent-soft/40" : "hover:bg-surface-2/40")}
    >
      {sortedSegments.map((seg, index) => {
        const group = FILM_STATE_GROUP[seg.state]
        const cfg = FILM_GROUP_CONFIG[group]
        const clippedStart = Math.max(seg.start, rangeStart)
        let clippedEnd = Math.min(seg.end, rangeEnd)
        const isLast = index === sortedSegments.length - 1
        if (!useApiMode && isLast && clippedEnd < rangeEnd) clippedEnd = rangeEnd
        const left = ((clippedStart - rangeStart) / windowMs) * totalWidthPx
        const width = Math.max(1.5, ((clippedEnd - clippedStart) / windowMs) * totalWidthPx)
        const dimmed = !stateFilter.has(group)
        const isSelected = seg.id === selectedSegmentId
        return (
          <div
            key={seg.id}
            title={`${cfg.label} · ${formatShortTime(seg.start)}–${formatShortTime(seg.end)}`}
            onClick={(e) => {
              e.stopPropagation()
              onSegmentClick(seg)
            }}
            className={cn(
              "absolute cursor-pointer rounded-none opacity-100 transition-opacity hover:brightness-95",
              "box-border border-r border-white/40",
              cfg.dot,
              dimmed && "opacity-20",
              isSelected && "ring-2 ring-inset ring-black/30"
            )}
            style={{ left, width: Math.max(2, width - 1), top: SEGMENT_INSET, bottom: SEGMENT_INSET }}
          />
        )
      })}
    </div>
  )
}

function DetailPanel({
  selection,
  equipment,
  allSegmentsByEquipment,
  rangeStart,
  rangeEnd,
  onOpenEquipment,
}: {
  selection: Selection
  equipment: ReturnType<typeof useSiteScopedEquipment>
  allSegmentsByEquipment: Map<string, TimelineSegment[]>
  rangeStart: number
  rangeEnd: number
  onOpenEquipment: (id: string) => void
}) {
  if (!selection) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 p-4 text-center">
        <p className="text-[11px] text-muted">
          Sélectionnez un segment ou un engin.
        </p>
      </div>
    )
  }

  const eq = equipment.find((e) => e.id === selection.equipmentId)
  if (!eq) return null

  if (selection.type === "segment") {
    const seg = selection.segment
    const group = FILM_STATE_GROUP[seg.state]
    const cfg = FILM_GROUP_CONFIG[group]
    const insight = filmSegmentInsight(seg.id, cfg.label)
    const unexplained = seg.state === "arret_indetermine"
    return (
      <div className="flex flex-col gap-2 p-3">
        <div className="border-b border-border pb-2">
          <p className="mb-1 flex items-center gap-2 text-[12px] font-semibold text-foreground">
            <span className={cn("size-2.5", cfg.dot)} />
            {cfg.label}
          </p>
          <p className="font-mono text-[11px] text-muted">
            {eq.code} · {formatTimeHms(seg.start)} → {formatTimeHms(seg.end)}
          </p>
          <p className="font-mono text-[11px] text-muted-2">
            Durée {formatElapsedHms(seg.end - seg.start)}
          </p>
          {seg.zoneName && <p className="mt-1 text-[11px] text-muted-2">Zone : {seg.zoneName}</p>}
        </div>
        <Tabs defaultValue="faits">
          <TabsList className="h-7 w-full rounded-lg bg-surface-2 p-0.5">
            <TabsTrigger value="faits" className="h-6 flex-1 text-[10px]">Faits</TabsTrigger>
            <TabsTrigger value="cause" className="h-6 flex-1 text-[10px]">Cause</TabsTrigger>
            <TabsTrigger value="ia" className="h-6 flex-1 text-[10px]">IA</TabsTrigger>
          </TabsList>
          <TabsContent value="faits" className="mt-2 space-y-1 text-[11px] text-muted">
            <p>État : {cfg.label}</p>
            <p>Début : {formatTimeHms(seg.start)}</p>
            <p>Fin : {formatTimeHms(seg.end)}</p>
            <p>Zone : {seg.zoneName ?? "—"}</p>
          </TabsContent>
          <TabsContent value="cause" className="mt-2 text-[11px] text-muted">
            {unexplained ? (
              <p className="text-danger">
                Arrêt sans cause déclarée — à classer (exploitation / matériel / extérieur).
              </p>
            ) : (
              <p>{useApiMode ? "Cause non renseignée. Un état équipement ne détermine pas une cause." : `Cause opérationnelle probable liée à l’état « ${cfg.label} » sur ce créneau.`}</p>
            )}
          </TabsContent>
          <TabsContent value="ia" className="mt-2">
            <AiSlot insight={insight} label="Pourquoi" />
          </TabsContent>
        </Tabs>
        <Button size="sm" className="h-7 rounded-xl" onClick={() => onOpenEquipment(eq.id)}>
          Ouvrir l'équipement
        </Button>
      </div>
    )
  }

  const mySegments = (allSegmentsByEquipment.get(eq.id) ?? []).sort((a, b) => a.start - b.start)
  return (
    <div className="flex flex-col gap-3 p-3">
      <div className="border-b border-border pb-2">
        <p className="font-mono text-[13px] font-semibold text-foreground">{eq.code}</p>
        <p className="text-[11px] text-muted">{eq.model}</p>
      </div>
      <div>
        <span className="mb-1 block text-[10px] font-semibold uppercase tracking-wide text-muted-2">
          Film du poste
        </span>
        <MiniTimelineStrip segments={mySegments} rangeStart={rangeStart} rangeEnd={rangeEnd} />
      </div>
      <div className="grid grid-cols-2 gap-2 border border-border bg-background p-2 text-[11px]">
        <div>
          <p className="text-muted-2">Voyages</p>
          <p className="font-mono font-semibold tabular-nums">{eq.tripsThisShift}</p>
        </div>
        <div>
          <p className="text-muted-2">Attente</p>
          <p className="font-mono font-semibold tabular-nums">{eq.waitingMinutesThisShift.toFixed(0)}m</p>
        </div>
      </div>
      <Button size="sm" className="h-7 rounded-xl" onClick={() => onOpenEquipment(eq.id)}>
        Ouvrir l'inspecteur
      </Button>
    </div>
  )
}
