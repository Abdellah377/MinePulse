import { useState, type ReactNode } from "react"
import { Check, UserPlus, Search } from "lucide-react"

import type { Alert } from "@/lib/mock/types"
import { ALERT_STATUS_LABEL } from "@/lib/mock/types"
import { SEVERITY_CONFIG, STATE_CONFIG } from "@/lib/status"
import { EquipmentTypeIcon } from "@/components/equipment/EquipmentTypeIcon"
import { formatShortTime, formatTimeHms, timeAgo } from "@/lib/format"
import { cn } from "@/lib/utils"
import { evenementInsight } from "@/lib/ai/placeholders"
import { shiftWindowBounds } from "@/lib/ops/shiftWindow"
import { useOpsStore } from "@/lib/store/useOpsStore"
import { useUiStore } from "@/lib/store/useUiStore"
import { AiSlot } from "@/components/ai/AiSlot"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { MiniTimelineStrip } from "@/components/equipment/MiniTimelineStrip"

export function EventInspector({ alert }: { alert: Alert }) {
  const equipment = useOpsStore((s) => s.equipment)
  const timelineSegments = useOpsStore((s) => s.timelineSegments)
  const shifts = useOpsStore((s) => s.shifts)
  const selectedShiftId = useOpsStore((s) => s.selectedShiftId)
  const simNowIso = useOpsStore((s) => s.simNowIso)
  const updateAlertStatus = useOpsStore((s) => s.updateAlertStatus)
  const openEquipmentDrawer = useUiStore((s) => s.openEquipmentDrawer)
  const [resolutionDraft, setResolutionDraft] = useState("")

  const cfg = SEVERITY_CONFIG[alert.severity]
  const eq = equipment.find((e) => e.id === alert.equipmentId)
  const eqCfg = eq ? STATE_CONFIG[eq.state] : null

  const segs = timelineSegments
    .filter((s) => s.equipmentId === alert.equipmentId)
    .sort((a, b) => a.start - b.start)

  const shift = shifts.find((s) => s.id === selectedShiftId) ?? shifts[0]
  const { startMs: shiftStart, nowMs: rangeEnd } = shiftWindowBounds(simNowIso, shift)

  const chronology = [
    { at: alert.createdAt, label: "Événement créé", detail: alert.title },
    ...(alert.status !== "new"
      ? [{ at: alert.updatedAt, label: `Statut → ${ALERT_STATUS_LABEL[alert.status]}`, detail: alert.assignedTo ?? "" }]
      : []),
    ...(alert.resolution
      ? [{ at: alert.updatedAt, label: "Résolu", detail: alert.resolution }]
      : []),
  ].sort((a, b) => a.at - b.at)

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <div className="shrink-0 border-b border-border px-4 py-3">
        <div className="mb-1 flex flex-wrap items-center gap-1.5">
          <Badge className={cn(cfg.bg, cfg.color, "border-transparent")}>{cfg.label}</Badge>
          <Badge variant="outline">{alert.category}</Badge>
          <Badge variant="outline">{ALERT_STATUS_LABEL[alert.status]}</Badge>
        </div>
        <h2 className="text-sm font-semibold text-foreground">{alert.title}</h2>
        <p className="mt-1 text-xs leading-relaxed text-muted">{alert.description}</p>
      </div>

      <Tabs defaultValue="resume" className="flex min-h-0 flex-1 flex-col">
        <TabsList className="mx-3 mt-2 h-8 w-auto justify-start self-start rounded-lg bg-surface-2 p-0.5">
          {(
            [
              ["resume", "Résumé"],
              ["chrono", "Chronologie"],
              ["equip", "Équipement"],
              ["analyse", "Analyse"],
              ["resolution", "Résolution"],
            ] as const
          ).map(([id, label]) => (
            <TabsTrigger key={id} value={id} className="h-7 rounded-md px-2.5 text-[11px]">
              {label}
            </TabsTrigger>
          ))}
        </TabsList>

        <div className="min-h-0 flex-1 overflow-y-auto">
          <TabsContent value="resume" className="mt-0 space-y-2 p-3">
            <FactGrid>
              <Fact label="Statut" value={ALERT_STATUS_LABEL[alert.status]} />
              <Fact label="Durée" value={timeAgo(alert.createdAt)} />
              <Fact label="Localisation" value={alert.location} />
              <Fact label="Équipement" value={eq?.code ?? "—"} />
              <Fact label="Impact" value={cfg.label} />
              <Fact label="Dernière màj" value={formatShortTime(alert.updatedAt)} />
              <Fact label="Assigné à" value={alert.assignedTo ?? "—"} />
              <Fact label="Catégorie" value={alert.category} />
            </FactGrid>
            {alert.status !== "resolved" && (
              <div className="flex flex-wrap gap-1.5 pt-1">
                <Button size="sm" variant="outline" onClick={() => updateAlertStatus(alert.id, "acknowledged")}>
                  Acquitter
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => updateAlertStatus(alert.id, "investigating", "Régulateur de poste")}
                >
                  En investigation
                </Button>
                {eq && (
                  <Button size="sm" onClick={() => openEquipmentDrawer(eq.id)}>
                    Ouvrir équipement
                  </Button>
                )}
              </div>
            )}
            {alert.resolution && (
              <p className="rounded-md border border-success/25 bg-success/10 px-3 py-2 text-[11px] text-success">
                {alert.resolution}
              </p>
            )}
          </TabsContent>

          <TabsContent value="chrono" className="mt-0 space-y-2 p-4">
            {chronology.map((c, i) => (
              <div key={i} className="flex gap-3 text-[11px]">
                <span className="w-14 shrink-0 font-mono tabular-nums text-muted-2">
                  {formatTimeHms(c.at)}
                </span>
                <div>
                  <p className="font-medium text-foreground">{c.label}</p>
                  {c.detail && <p className="text-muted">{c.detail}</p>}
                </div>
              </div>
            ))}
            {eq && segs.length > 0 && (
              <div className="pt-2">
                <p className="mb-1 text-[10px] font-semibold uppercase text-muted-2">Film équipement</p>
                <MiniTimelineStrip segments={segs} rangeStart={shiftStart} rangeEnd={rangeEnd} />
              </div>
            )}
          </TabsContent>

          <TabsContent value="equip" className="mt-0 space-y-3 p-4">
            {eq && eqCfg ? (
              <>
                <div className="flex items-center gap-2">
                  <div className={cn("flex size-9 items-center justify-center rounded-lg p-0.5", eqCfg.bg)}>
                    <EquipmentTypeIcon type={eq.type} className="size-8" title={eq.code} />
                  </div>
                  <div>
                    <p className="font-mono text-sm font-semibold">{eq.code}</p>
                    <p className="text-[11px] text-muted">{eq.model}</p>
                  </div>
                </div>
                <Badge className={cn(eqCfg.bg, eqCfg.color, "w-fit border-transparent")}>
                  {eqCfg.label}
                </Badge>
                <Button size="sm" onClick={() => openEquipmentDrawer(eq.id)}>
                  Ouvrir l'inspecteur équipement
                </Button>
              </>
            ) : (
              <p className="text-xs text-muted">Événement de zone — aucun équipement lié.</p>
            )}
          </TabsContent>

          <TabsContent value="analyse" className="mt-0 p-4">
            <AiSlot insight={evenementInsight(alert.id, alert.category)} label="Explication" />
          </TabsContent>

          <TabsContent value="resolution" className="mt-0 space-y-3 p-4">
            {alert.status === "resolved" ? (
              <div className="rounded-xl border border-success/25 bg-success/10 px-3 py-2 text-[11px] text-success">
                Événement résolu{alert.resolution ? ` — ${alert.resolution}` : "."}
              </div>
            ) : (
              <>
                <div className="flex flex-wrap gap-1.5">
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => updateAlertStatus(alert.id, "acknowledged")}
                  >
                    Acquitter
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() =>
                      updateAlertStatus(alert.id, "investigating", "Régulateur de poste")
                    }
                  >
                    <Search className="size-3.5" />
                    En investigation
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() =>
                      updateAlertStatus(alert.id, "assigned", "Régulateur de poste")
                    }
                  >
                    <UserPlus className="size-3.5" />
                    Assigner
                  </Button>
                </div>
                <Textarea
                  rows={3}
                  placeholder="Notes de résolution…"
                  value={resolutionDraft}
                  onChange={(e) => setResolutionDraft(e.target.value)}
                />
                <Button
                  size="sm"
                  onClick={() => {
                    updateAlertStatus(alert.id, "resolved")
                    setResolutionDraft("")
                  }}
                >
                  <Check className="size-3.5" />
                  Marquer résolu
                </Button>
              </>
            )}
          </TabsContent>
        </div>
      </Tabs>
    </div>
  )
}

function FactGrid({ children }: { children: ReactNode }) {
  return <div className="flex flex-col gap-2 rounded-xl border border-border bg-surface-2/40 p-3">{children}</div>
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-start justify-between gap-3 text-[11px]">
      <span className="text-muted-2">{label}</span>
      <span className="text-right text-foreground/90">{value}</span>
    </div>
  )
}
