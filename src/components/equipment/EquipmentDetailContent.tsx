import { useEffect, useMemo, useState } from "react"
import {
  Gauge,
  Fuel,
  Power,
  MapPin,
  Map as MapIcon,
  User,
  Wrench,
  TrendingUp,
  ExternalLink,
  Film,
  Bell,
  Route,
} from "lucide-react"

import { useOpsStore } from "@/lib/store/useOpsStore"
import { fetchEquipmentDetail, useApiMode, type EquipmentMaintenanceRow } from "@/lib/api/client"
import type { FailureRiskDto } from "@/lib/api/types/ops"
import { demoFailureRisk, failureRiskView } from "@/lib/equipment/failureRisk"
import { FailureRiskCard } from "@/components/equipment/FailureRiskCard"
import { shiftWindowBounds } from "@/lib/ops/shiftWindow"
import { useUiStore } from "@/lib/store/useUiStore"
import { useWorkspaceStore } from "@/lib/store/useWorkspaceStore"
import { openMapForTarget } from "@/lib/workspace/openMapFocus"
import { STATE_CONFIG } from "@/lib/status"
import { EquipmentTypeIcon } from "@/components/equipment/EquipmentTypeIcon"
import type { EquipmentState } from "@/lib/mock/types"
import { timeAgo } from "@/lib/format"
import { formatPosteName } from "@/lib/ops/shiftLabel"
import { cn } from "@/lib/utils"
import { cycleLongInsight, inspecteurInsight } from "@/lib/ai/placeholders"
import { AiSlot } from "@/components/ai/AiSlot"
import { Badge } from "@/components/ui/badge"
import { Separator } from "@/components/ui/separator"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Button } from "@/components/ui/button"
import { MiniTimelineStrip } from "@/components/equipment/MiniTimelineStrip"
import { CycleStepper } from "@/components/parc/CycleStepper"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { DataFreshnessIndicator } from "@/components/shared/DataFreshnessIndicator"
import { formatEquipmentContribution } from "@/lib/equipment/contribution"

function taskDescription(state: EquipmentState, zoneName: string | null, destName: string | null) {
  switch (state) {
    case "mouvement_charge":
      return `En route vers ${destName ?? (useApiMode ? "une destination non renseignée" : "le déchargement")}`
    case "mouvement_vide":
      return `Retour vers ${destName ?? (useApiMode ? "une destination non renseignée" : "le banc de chargement")}`
    case "chargement":
      return `Chargement à ${zoneName ?? "la zone"}`
    case "dechargement":
      return `Déchargement à ${zoneName ?? "la zone"}`
    case "attente_charge":
      return `Attente de chargement à ${zoneName ?? "la zone"}`
    case "attente_dechargement":
      return `Attente de déchargement à ${zoneName ?? "la zone"}`
    case "eteint":
      return "Éteint — aucune activité"
    default:
      return "Activité non déterminée"
  }
}

const MAINTENANCE_TYPES = [
  "Entretien 250 heures",
  "Rotation des pneus",
  "Contrôle circuit hydraulique",
  "Vidange moteur",
  "Inspection des freins",
  "Inspection du châssis",
]

function hashSeed(id: string) {
  let h = 0
  for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) >>> 0
  return h
}

function buildMaintenanceHistory(id: string) {
  const seed = hashSeed(id)
  const count = 2 + (seed % 3)
  return Array.from({ length: count }).map((_, i) => {
    const daysAgo = 6 + ((seed >> (i + 2)) % 40)
    const type = MAINTENANCE_TYPES[(seed + i * 7) % MAINTENANCE_TYPES.length]
    const durationH = 1 + ((seed >> (i + 1)) % 6)
    return {
      id: `${id}-mnt-${i}`,
      date: Date.now() - daysAgo * 86_400_000,
      type,
      durationH,
      technician: ["Atelier A", "Atelier B", "Maintenance", "Contrôle qualité"][(seed + i) % 4],
    }
  })
}

export function EquipmentDetailContent({
  equipmentId,
  showExpand,
  onExpand,
  onShowRecentPath,
}: {
  equipmentId: string
  showExpand?: boolean
  onExpand?: () => void
  onShowRecentPath?: () => void
}) {
  const closeEquipmentDrawer = useUiStore((s) => s.closeEquipmentDrawer)
  const openWorkspace = useWorkspaceStore((s) => s.openWorkspace)
  const equipment = useOpsStore((s) => s.equipment)
  const operators = useOpsStore((s) => s.operators)
  const zones = useOpsStore((s) => s.zones)
  const timelineSegments = useOpsStore((s) => s.timelineSegments)
  const simNowIso = useOpsStore((s) => s.simNowIso)
  const patchEquipment = useOpsStore((s) => s.patchEquipment)
  const shifts = useOpsStore((s) => s.shifts)
  const selectedShiftId = useOpsStore((s) => s.selectedShiftId)
  const selectedSiteId = useOpsStore((s) => s.selectedSiteId)

  const [maintenanceRows, setMaintenanceRows] = useState<EquipmentMaintenanceRow[] | null>(null)
  const [apiFailureRisk, setApiFailureRisk] = useState<FailureRiskDto | null>(null)
  const [detailError, setDetailError] = useState<string | null>(null)
  const [detailLoading, setDetailLoading] = useState(useApiMode)

  useEffect(() => {
    if (!useApiMode) {
      setMaintenanceRows(null)
      setApiFailureRisk(null)
      setDetailError(null)
      setDetailLoading(false)
      return
    }
    let cancelled = false
    setDetailError(null)
    setMaintenanceRows(null)
    setApiFailureRisk(null)
    setDetailLoading(true)
    void fetchEquipmentDetail(equipmentId, {
      siteCode: selectedSiteId,
      shiftId: selectedShiftId,
    })
      .then((detail) => {
        if (cancelled) return
        patchEquipment(detail.equipment)
        setMaintenanceRows(detail.maintenanceHistory)
        setApiFailureRisk(detail.failureRisk)
        setDetailLoading(false)
      })
      .catch(() => {
        if (!cancelled) {
          setDetailError("Impossible de charger le détail équipement.")
          setDetailLoading(false)
        }
      })
    return () => {
      cancelled = true
    }
  }, [equipmentId, patchEquipment, selectedSiteId, selectedShiftId])

  const eq = equipment.find((e) => e.id === equipmentId)
  const operator = operators.find((o) => o.id === eq?.operatorId)
  const zone = zones.find((z) => z.id === eq?.zoneId)
  const destZone = zones.find((z) => z.id === eq?.destinationZoneId)
  const shift = shifts.find((s) => s.id === selectedShiftId)
  const { startMs: rangeStart, nowMs: rangeEnd } = shiftWindowBounds(simNowIso, shift)

  const mySegments = useMemo(
    () => timelineSegments.filter((s) => s.equipmentId === equipmentId).sort((a, b) => a.start - b.start),
    [timelineSegments, equipmentId]
  )

  const maintenanceHistory = useMemo(() => {
    if (useApiMode) return maintenanceRows ?? []
    return buildMaintenanceHistory(equipmentId)
  }, [equipmentId, maintenanceRows])

  if (!eq) {
    return <div className="p-5 text-xs text-muted">Équipement introuvable.</div>
  }

  const cfg = STATE_CONFIG[eq.state]
  const now = rangeEnd
  const failureRisk = useApiMode ? apiFailureRisk : eq.type === "haul_truck" ? demoFailureRisk(eq.id) : null
  const riskView = failureRiskView({
    apiMode: useApiMode,
    equipmentType: eq.type,
    loading: detailLoading,
    error: detailError,
    prediction: failureRisk,
  })

  const shiftElapsedMin = Math.max(1, (rangeEnd - rangeStart) / 60_000)
  const waitingPct = useApiMode ? NaN : (eq.waitingMinutesThisShift / shiftElapsedMin) * 100
  const idlePct = useApiMode ? NaN : (eq.idleMinutesThisShift / shiftElapsedMin) * 100

  const insight = inspecteurInsight(eq.id, eq.code)

  return (
    <div className="flex h-full flex-col">
      {detailError && (
        <div className="border-b border-danger/30 bg-danger/10 px-5 py-2 text-xs text-danger">
          {detailError}
        </div>
      )}
      <div className="flex flex-col gap-3 border-b border-border px-5 py-4">
        <div className="flex items-start gap-3">
          <div className={cn("flex size-10 shrink-0 items-center justify-center rounded-lg p-1", cfg.bg)}>
            <EquipmentTypeIcon type={eq.type} className="size-8" title={eq.code} />
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <h2 className="font-mono text-base font-semibold text-foreground">{eq.code}</h2>
              <Badge className={cn(cfg.bg, cfg.color, "border-transparent")}>{cfg.label}</Badge>
            </div>
            <p className="truncate text-xs text-muted">{eq.model}</p>
          </div>
          {showExpand && (
            <Button variant="ghost" size="icon" onClick={onExpand}>
              <ExternalLink className="size-3.5" />
            </Button>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-3 text-[11px] text-muted">
          <span className="flex items-center gap-1.5">
            <User className="size-3.5 text-muted-2" />
            {operator ? operator.name : useApiMode ? "Opérateur non renseigné" : "Non affecté"}
          </span>
          <span className="flex items-center gap-1.5">
            <MapPin className="size-3.5 text-muted-2" />
            {zone ? zone.name : "Zone inconnue"}
          </span>
          {shift && <Badge variant="outline">{formatPosteName(shift.name)}</Badge>}
        </div>

        <div className="rounded-md border border-border bg-surface-2/50 px-3 py-2 text-xs text-foreground/90">
          {taskDescription(eq.state, zone?.name ?? null, destZone?.name ?? null)}
        </div>

        <div className="flex flex-wrap gap-1.5">
          <Button
            size="sm"
            variant="outline"
            onClick={() => {
              closeEquipmentDrawer()
              openMapForTarget({
                equipmentId: eq.id,
                equipmentCode: eq.code,
                zoneId: eq.zoneId ?? undefined,
                zoneName: zone?.name,
              })
            }}
          >
            <MapIcon className="size-3.5" />
            Voir sur la carte
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={() => {
              closeEquipmentDrawer()
              openWorkspace({
                type: "timeline",
                context: { equipmentId: eq.id, equipmentCode: eq.code },
              })
            }}
          >
            <Film className="size-3.5" />
            Voir dans le Film
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={() => {
              closeEquipmentDrawer()
              openWorkspace({ type: "alerts", context: { equipmentId: eq.id, equipmentCode: eq.code } })
            }}
          >
            <Bell className="size-3.5" />
            Voir les événements
          </Button>
          {onShowRecentPath && !useApiMode && (
            <Button size="sm" variant="outline" onClick={onShowRecentPath}>
              <Route className="size-3.5" />
              Afficher le trajet récent
            </Button>
          )}
        </div>

        <div className="flex items-center justify-between text-[11px] text-muted">
          <span>Dernière position / télémétrie · {eq.lastUpdate == null ? "Indisponible" : timeAgo(eq.lastUpdate, Number.isFinite(now) ? now : Date.now())}</span>
          <DataFreshnessIndicator />
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        <Tabs defaultValue="apercu" className="h-full">
          <div className="border-b border-border px-5 pt-3">
            <TabsList>
              <TabsTrigger value="apercu">Aperçu</TabsTrigger>
              <TabsTrigger value="cycle">Cycle</TabsTrigger>
              <TabsTrigger value="kpis">KPIs</TabsTrigger>
              <TabsTrigger value="maintenance">Maint.</TabsTrigger>
              <TabsTrigger value="ia">IA</TabsTrigger>
            </TabsList>
          </div>

          <TabsContent value="apercu" className="flex flex-col gap-4 px-5 py-4">
            <div className="grid grid-cols-2 gap-2.5">
              <TelemetryStat icon={Gauge} label="Vitesse" value={eq.speedKmh != null ? `${eq.speedKmh.toFixed(0)} km/h` : "—"} />
              <TelemetryStat
                icon={Fuel}
                label="Gasoil"
                value={eq.fuelPct != null ? `${eq.fuelPct.toFixed(0)}%` : "—"}
                tone={
                  useApiMode || eq.fuelPct == null
                    ? "default"
                    : eq.fuelPct < 25
                      ? "danger"
                      : eq.fuelPct < 50
                        ? "warning"
                        : "default"
                }
              />
              <TelemetryStat
                icon={Power}
                label="Moteur"
                value={eq.engineOn == null ? "—" : eq.engineOn ? "En marche" : "Coupé"}
                tone={eq.engineOn ? "success" : "default"}
              />
              <TelemetryStat
                icon={TrendingUp}
                label="Santé"
                value={eq.healthScore == null ? "—" : eq.healthScore.toFixed(0)}
              />
            </div>

            <div>
              <span className="mb-1.5 block text-[10px] font-semibold uppercase tracking-wider text-muted-2">
                Mini-film du poste
              </span>
              <MiniTimelineStrip segments={mySegments} rangeStart={rangeStart} rangeEnd={rangeEnd} />
            </div>

            <Separator />

            <div className="grid grid-cols-2 gap-3 text-xs">
              <Stat label="NV (voyages) ce poste" value={`${eq.tripsThisShift}`} />
              <Stat
                label="Charge"
                value={
                  eq.payloadTons != null && eq.capacityTons != null
                    ? `${eq.payloadTons.toFixed(0)} / ${eq.capacityTons} t`
                    : eq.payloadTons != null
                      ? `${eq.payloadTons.toFixed(0)} t`
                      : "—"
                }
              />
              <Stat
                label="Odomètre"
                value={eq.odometerKm != null ? `${eq.odometerKm.toFixed(0)} km` : "—"}
              />
              <Stat
                label="Heures moteur"
                value={eq.engineHours != null ? `${eq.engineHours.toFixed(0)} h` : "—"}
              />
            </div>
          </TabsContent>

          <TabsContent value="cycle" className="flex flex-col gap-3 px-5 py-4">
            <CycleStepper stages={eq.cycleActuel} dureeMoyenneMin={eq.cycleDureeMoyenneMin} />
            <AiSlot insight={cycleLongInsight(eq.id)} label="Cycle" />
          </TabsContent>

          <TabsContent value="kpis" className="flex flex-col gap-3 px-5 py-4">
            <div className="grid grid-cols-2 gap-2.5">
              <TelemetryStat
                icon={TrendingUp}
                label="TD (disponibilité)"
                value={eq.tdPct == null ? "—" : `${eq.tdPct.toFixed(0)}%`}
              />
              <TelemetryStat
                icon={Gauge}
                label="TU (utilisation)"
                value={eq.tuPct == null ? "—" : `${eq.tuPct.toFixed(0)}%`}
              />
              <TelemetryStat
                icon={Gauge}
                label={useApiMode ? "Attente cumulée poste" : "Attente %"}
                value={useApiMode ? `${eq.waitingMinutesThisShift} min` : `${waitingPct.toFixed(0)}%`}
                tone={waitingPct > 25 ? "danger" : waitingPct > 12 ? "warning" : "default"}
              />
              <TelemetryStat
                icon={Gauge}
                label={useApiMode ? "Idle cumulé poste" : "Idle %"}
                value={useApiMode ? `${eq.idleMinutesThisShift} min` : `${idlePct.toFixed(0)}%`}
                tone={idlePct > 20 ? "danger" : idlePct > 10 ? "warning" : "default"}
              />
            </div>
            <div className="rounded-md border border-border bg-surface-2/40 p-3">
              <p className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-2">
                Attente vs Idle vs Actif
              </p>
              {useApiMode ? <p className="text-xs text-muted">Répartition en pourcentage non fournie par le backend.</p> : <div className="flex h-2.5 overflow-hidden rounded-full bg-surface-3">
                <div className="h-full bg-state-attente" style={{ width: `${Math.min(100, waitingPct)}%` }} />
                <div className="h-full bg-state-arret" style={{ width: `${Math.min(100 - waitingPct, idlePct)}%` }} />
                <div
                  className="h-full bg-state-mouvement-charge"
                  style={{ width: `${Math.max(0, 100 - waitingPct - idlePct)}%` }}
                />
              </div>}
            </div>
            <Stat label="Contribution production" value={formatEquipmentContribution(eq)} />
          </TabsContent>

          <TabsContent value="maintenance" className="flex flex-col gap-3 px-5 py-4">
            <div className="flex items-center justify-between rounded-md border border-border bg-surface-2/40 px-3 py-2">
              <div className="flex items-center gap-2 text-xs text-foreground/90">
                <Wrench className="size-3.5 text-muted-2" />
                Prochain entretien
              </div>
              <span className="text-xs text-muted">
                {useApiMode ? "Non évalué" : eq.engineHours != null
                  ? `dans ${(250 - (eq.engineHours % 250)).toFixed(0)} heures moteur`
                  : "—"}
              </span>
            </div>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Date</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>Technicien</TableHead>
                  <TableHead>Durée</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {maintenanceHistory.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={4} className="text-center text-muted-2">
                      {detailError ? "Historique indisponible." : useApiMode && maintenanceRows == null ? "Chargement de l’historique…" : "Aucun entretien enregistré pour cet engin."}
                    </TableCell>
                  </TableRow>
                ) : null}
                {maintenanceHistory.map((m) => (
                  <TableRow key={m.id}>
                    <TableCell className="text-muted-2">{timeAgo(m.date, now)}</TableCell>
                    <TableCell className="text-foreground/90">{m.type}</TableCell>
                    <TableCell className="text-muted">{m.technician ?? "—"}</TableCell>
                    <TableCell className="tabular-nums">{m.durationH == null ? "—" : `${m.durationH} h`}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TabsContent>

          <TabsContent value="ia" className="flex flex-col gap-3 px-5 py-4">
            {riskView.kind === "loading" && <FailureRiskCard loading />}
            {riskView.kind === "error" && <FailureRiskCard error={riskView.message} />}
            {riskView.kind === "ready" && <FailureRiskCard prediction={riskView.prediction} />}
            <AiSlot insight={insight} label="Pourquoi" />
          </TabsContent>
        </Tabs>
      </div>
    </div>
  )
}

function TelemetryStat({
  icon: IconCmp,
  label,
  value,
  tone = "default",
}: {
  icon: typeof Gauge
  label: string
  value: string
  tone?: "default" | "success" | "warning" | "danger"
}) {
  const toneColor =
    tone === "success"
      ? "text-success"
      : tone === "warning"
        ? "text-warning"
        : tone === "danger"
          ? "text-danger"
          : "text-foreground"
  return (
    <div className="flex items-center gap-2.5 rounded-md border border-border bg-surface-2/40 px-2.5 py-2">
      <IconCmp className="size-3.5 shrink-0 text-muted-2" />
      <div className="flex flex-col">
        <span className="text-[9px] uppercase tracking-wider text-muted-2">{label}</span>
        <span className={cn("text-xs font-semibold tabular-nums", toneColor)}>{value}</span>
      </div>
    </div>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-[10px] uppercase tracking-wider text-muted-2">{label}</p>
      <p className="font-medium tabular-nums text-foreground/90">{value}</p>
    </div>
  )
}
