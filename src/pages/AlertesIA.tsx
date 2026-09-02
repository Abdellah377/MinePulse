import { useEffect, useMemo, useState } from "react"
import {
  Map as MapIcon,
  Film as FilmIcon,
  Truck,
  Sparkles,
  Inbox,
} from "lucide-react"

import { useOpsStore, useSiteScopedEquipment, useSiteScopedZones } from "@/lib/store/useOpsStore"
import { useApiMode } from "@/lib/api/client"
import { useUiStore } from "@/lib/store/useUiStore"
import { useWorkspaceStore } from "@/lib/store/useWorkspaceStore"
import { openMapForTarget } from "@/lib/workspace/openMapFocus"
import { SEVERITY_CONFIG } from "@/lib/status"
import { cn } from "@/lib/utils"
import type { AlertSeverity } from "@/lib/mock/types"
import {
  actionsContextFromItem,
  buildCurrentIntelligence,
  buildPredictionIntelligence,
  type AlertKind,
  type IntelligenceItem,
} from "@/lib/ai/alertIntelligence"
import type { WorkspacePanelProps } from "@/components/workspace/WorkspaceHost"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { MiniTimelineStrip } from "@/components/equipment/MiniTimelineStrip"
import { InvestigationAlerts } from "@/components/ai/InvestigationAlerts"
import { Section, Fact } from "@/components/ai/InvestigationLayout"
import { DISCLOSURE_SUMMARY_CLASS } from "@/components/ai/EvidenceCard"

type SeverityFilter = "all" | AlertSeverity

export default function AlertesIA(props: Partial<WorkspacePanelProps> = {}) {
  return useApiMode ? <InvestigationAlerts {...props} /> : <DemoAlertesIA {...props} />
}

/** Scenario intelligence is intentionally confined to demo mode. */
function DemoAlertesIA({ tab }: Partial<WorkspacePanelProps> = {}) {
  const alerts = useOpsStore((s) => s.alerts)
  const equipment = useSiteScopedEquipment()
  const zones = useSiteScopedZones()
  const timelineSegments = useOpsStore((s) => s.timelineSegments)
  const simNowIso = useOpsStore((s) => s.simNowIso)
  const openEquipmentDrawer = useUiStore((s) => s.openEquipmentDrawer)
  const openWorkspace = useWorkspaceStore((s) => s.openWorkspace)
  const setTabState = useWorkspaceStore((s) => s.setTabState)

  const [mode, setMode] = useState<AlertKind>("current")
  const [severityFilter, setSeverityFilter] = useState<SeverityFilter>("all")
  const [zoneFilter, setZoneFilter] = useState("all")
  const [selectedId, setSelectedId] = useState<string | null>(
    tab?.context.alertId ?? tab?.context.predictionId ?? null
  )

  const currentItems = useMemo(
    () => buildCurrentIntelligence(alerts, equipment, zones, simNowIso),
    [alerts, equipment, zones, simNowIso]
  )
  const predictionItems = useMemo(
    () => (useApiMode ? [] : buildPredictionIntelligence()),
    []
  )

  const items = useMemo(() => {
    const base = mode === "current" ? currentItems : predictionItems
    return base
      .filter((i) => severityFilter === "all" || i.severity === severityFilter)
      .filter((i) => zoneFilter === "all" || i.zoneName === zoneFilter || i.zoneId === zoneFilter)
  }, [mode, currentItems, predictionItems, severityFilter, zoneFilter])

  const selected = items.find((i) => i.id === selectedId) ?? items[0] ?? null

  useEffect(() => {
    if (tab?.context.alertId) {
      setMode("current")
      setSelectedId(tab.context.alertId)
    } else if (tab?.context.predictionId) {
      setMode("prediction")
      setSelectedId(tab.context.predictionId)
    }
  }, [tab?.id, tab?.context.alertId, tab?.context.predictionId])

  useEffect(() => {
    if (!tab?.id) return
    setTabState(tab.id, { mode, selectedId: selected?.id, severityFilter, zoneFilter })
  }, [tab?.id, mode, selected?.id, severityFilter, zoneFilter, setTabState])

  const segs = useMemo(() => {
    if (!selected?.equipmentId) return []
    return timelineSegments
      .filter((s) => s.equipmentId === selected.equipmentId)
      .sort((a, b) => a.start - b.start)
      .slice(-10)
  }, [timelineSegments, selected?.equipmentId])

  const zoneNames = useMemo(() => {
    const set = new Set<string>()
    ;[...currentItems, ...predictionItems].forEach((i) => {
      if (i.zoneName) set.add(i.zoneName)
    })
    return Array.from(set)
  }, [currentItems, predictionItems])

  function openActions(item: IntelligenceItem) {
    const ctx = actionsContextFromItem(item)
    openWorkspace({
      type: "actions",
      investigationId: ctx.investigationId,
      context: ctx,
      title: `Actions IA — ${ctx.titleFocus ?? item.category}`,
    })
  }

  return (
    <div className="flex h-full overflow-hidden">
      {/* List */}
      <aside className="flex w-[28%] min-w-[260px] max-w-[360px] flex-col border-r border-border bg-surface">
        <div className="shrink-0 space-y-2 border-b border-border px-3 py-2.5">
          <div className="flex rounded-md bg-surface-2 p-0.5">
            {(
              [
                ["current", "En cours", currentItems.length],
                ["prediction", "Prédictions", predictionItems.length],
              ] as const
            ).map(([id, label, count]) => (
              <button
                key={id}
                type="button"
                onClick={() => {
                  setMode(id)
                  setSelectedId(null)
                }}
                className={cn(
                  "flex h-7 flex-1 items-center justify-center gap-1 rounded-md text-[11px] font-medium",
                  mode === id ? "bg-surface text-foreground shadow-sm" : "text-muted"
                )}
              >
                {label}
                <span className="text-[10px] text-muted-2">{count}</span>
              </button>
            ))}
          </div>
          <div className="flex flex-wrap gap-1">
            {(["all", "critical", "warning", "info"] as SeverityFilter[]).map((f) => (
              <button
                key={f}
                type="button"
                onClick={() => setSeverityFilter(f)}
                className={cn(
                  "h-6 rounded-md px-2 text-[10px] font-medium",
                  severityFilter === f ? "bg-accent text-white" : "bg-surface-2 text-muted"
                )}
              >
                {f === "all" ? "Tous" : SEVERITY_CONFIG[f].label}
              </button>
            ))}
            <select
              className="h-6 max-w-[110px] rounded-md border border-border bg-background px-1 text-[10px]"
              value={zoneFilter}
              onChange={(e) => setZoneFilter(e.target.value)}
            >
              <option value="all">Zone</option>
              {zoneNames.map((z) => (
                <option key={z} value={z}>
                  {z}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto">
          {items.length === 0 && (
            <div className="flex flex-col items-center gap-2 py-16 text-center">
              <Inbox className="size-5 text-muted-2" />
              <p className="text-xs text-muted">Aucune alerte.</p>
            </div>
          )}
          {items.map((item) => {
            const cfg = SEVERITY_CONFIG[item.severity]
            const active = selected?.id === item.id
            return (
              <button
                key={item.id}
                type="button"
                onClick={() => setSelectedId(item.id)}
                className={cn(
                  "flex w-full flex-col gap-0.5 border-b border-border px-3 py-2.5 text-left",
                  active ? "bg-accent-soft/50" : "hover:bg-surface-2/70"
                )}
              >
                <div className="flex items-center gap-1.5 text-[10px]">
                  <span className={cn("size-1.5 rounded-full", cfg.dot)} />
                  <span className={cn("font-semibold", cfg.color)}>{cfg.label}</span>
                  <span className="text-muted-2">{item.category}</span>
                  <span className="ml-auto tabular-nums text-muted-2">{item.timeLabel}</span>
                </div>
                <p className="text-[12px] font-medium text-foreground">{item.title}</p>
                <p className="line-clamp-1 text-[11px] text-muted">{item.summary}</p>
                <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[10px] text-muted-2">
                  {item.equipmentCode && (
                    <span className="font-mono font-semibold text-foreground/80">{item.equipmentCode}</span>
                  )}
                  {item.zoneName && <span>{item.zoneName}</span>}
                  <span>Conf. {item.confidence}%</span>
                  <span>{item.statusLabel}</span>
                </div>
              </button>
            )
          })}
        </div>
      </aside>

      {/* Detail */}
      <main className="min-w-0 flex-1 overflow-y-auto border-r border-border bg-background p-4">
        {!selected ? (
          <p className="text-xs text-muted">Sélectionnez une alerte.</p>
        ) : (
          <div className="mx-auto max-w-2xl space-y-4">
            <header>
              <div className="mb-1 flex flex-wrap gap-1.5">
                <Badge
                  className={cn(
                    SEVERITY_CONFIG[selected.severity].bg,
                    SEVERITY_CONFIG[selected.severity].color,
                    "border-transparent"
                  )}
                >
                  {SEVERITY_CONFIG[selected.severity].label}
                </Badge>
                <Badge variant="outline">{selected.category}</Badge>
                <Badge variant="outline">
                  {selected.kind === "prediction" ? "Prédiction" : "En cours"}
                </Badge>
                <Badge variant="outline">{selected.statusLabel}</Badge>
              </div>
              <h2 className="text-[16px] font-semibold text-foreground">{selected.title}</h2>
              <p className="mt-1 text-[12px] leading-relaxed text-muted">{selected.summary}</p>
              <dl className="mt-2 grid grid-cols-2 gap-2 text-[11px]">
                <Fact label="Où" value={selected.zoneName ?? "—"} />
                <Fact
                  label={selected.kind === "prediction" ? "Horizon" : "Depuis"}
                  value={selected.timeLabel}
                />
                <Fact label="Équipement" value={selected.equipmentCode ?? "—"} mono />
              </dl>
            </header>

            <Section title="Conclusion">
              <h3 className="text-[15px] font-semibold leading-snug text-foreground">{selected.probableCause}</h3>
              <p className="mt-1 text-[11px] text-muted">Confiance : {selected.confidence} %</p>
            </Section>

            <Section title="Pourquoi MinePulse pense cela">
              <ul className="list-inside list-disc text-[12px] text-muted">
                {selected.signals.slice(0, 3).map((s) => (
                  <li key={s}>{s}</li>
                ))}
              </ul>
              {selected.signals.length > 3 && (
                <details className="mt-2">
                  <summary className={DISCLOSURE_SUMMARY_CLASS}>
                    Voir {selected.signals.length - 3} autre{selected.signals.length - 3 === 1 ? "" : "s"} élément{selected.signals.length - 3 === 1 ? "" : "s"}
                  </summary>
                  <ul className="mt-1 list-inside list-disc text-[12px] text-muted">
                    {selected.signals.slice(3).map((s) => (
                      <li key={s}>{s}</li>
                    ))}
                  </ul>
                </details>
              )}
            </Section>

            <Section title="Action recommandée">
              <p className="text-[13px] font-semibold leading-relaxed text-foreground">{selected.suggestedAction}</p>
              <p className="mt-2 text-[10px] font-medium text-foreground">Validation humaine requise · aucune action automatique</p>
            </Section>

            <details data-testid="investigation-details" className="rounded-md border border-border bg-surface">
              <summary className={cn(DISCLOSURE_SUMMARY_CLASS, "text-[12px]")}>
                Détails de l’investigation
              </summary>
              <div className="space-y-3 border-t border-border p-3">
                {selected.impact && (
                  <section>
                    <h4 className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-muted-2">Impact estimé</h4>
                    <p className="text-[12px] text-muted">{selected.impact}</p>
                    <p className="mt-1 text-[11px] text-muted-2">Si ignoré : {selected.ifIgnored}</p>
                  </section>
                )}
                {selected.signals.length > 0 && (
                  <section>
                    <h4 className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-muted-2">Preuves complètes</h4>
                    <ul className="list-inside list-disc text-[11px] text-muted">
                      {selected.signals.map((s) => (
                        <li key={s}>{s}</li>
                      ))}
                    </ul>
                  </section>
                )}
              </div>
            </details>

            {segs.length > 0 && (
              <details className="rounded-md border border-border bg-surface">
                <summary className={DISCLOSURE_SUMMARY_CLASS}>Film récent</summary>
                <div className="border-t border-border p-3">
                  <MiniTimelineStrip
                    segments={segs}
                    rangeStart={segs[0].start}
                    rangeEnd={simNowIso ? new Date(simNowIso).getTime() : segs[segs.length - 1]?.end ?? Date.now()}
                  />
                </div>
              </details>
            )}
            <details className="rounded-md border border-border bg-surface">
              <summary className={DISCLOSURE_SUMMARY_CLASS}>Liens utiles</summary>
              <div className="flex flex-col gap-1.5 border-t border-border p-3">
                <Button
                  size="sm"
                  variant="outline"
                  className="justify-start"
                  onClick={() =>
                    openMapForTarget({
                      equipmentId: selected.equipmentId ?? undefined,
                      equipmentCode: selected.equipmentCode ?? undefined,
                      zoneId: selected.zoneId ?? undefined,
                      zoneName: selected.zoneName ?? undefined,
                    })
                  }
                >
                  <MapIcon className="size-3.5" />
                  Ouvrir la Carte
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  className="justify-start"
                  disabled={!selected.equipmentId && !selected.equipmentCode}
                  onClick={() => {
                    const eq =
                      equipment.find((e) => e.id === selected.equipmentId) ??
                      equipment.find((e) => e.code === selected.equipmentCode)
                    if (!eq) return
                    openWorkspace({
                      type: "timeline",
                      investigationId: `inv-${selected.id}`,
                      context: {
                        equipmentId: eq.id,
                        equipmentCode: eq.code,
                        investigationId: `inv-${selected.id}`,
                      },
                    })
                  }}
                >
                  <FilmIcon className="size-3.5" />
                  Ouvrir le Film
                </Button>
                {(selected.equipmentId || selected.equipmentCode) && (
                  <Button
                    size="sm"
                    variant="outline"
                    className="justify-start"
                    onClick={() => {
                      const eq =
                        equipment.find((e) => e.id === selected.equipmentId) ??
                        equipment.find((e) => e.code === selected.equipmentCode)
                      if (eq) openEquipmentDrawer(eq.id)
                    }}
                  >
                    <Truck className="size-3.5" />
                    Ouvrir l&apos;équipement
                  </Button>
                )}
              </div>
            </details>
          </div>
        )}
      </main>

      <aside className="flex w-[28%] min-w-[240px] max-w-[340px] flex-col overflow-y-auto bg-surface p-4">
        {selected ? (
          <>
            <h3 className="text-[11px] font-semibold uppercase tracking-wide text-muted-2">
              Panel IA
            </h3>
            <Button className="mt-4 w-full gap-1.5" onClick={() => openActions(selected)}>
              <Sparkles className="size-3.5" />
              Générer des solutions IA
            </Button>
            <p className="mt-2 text-[10px] leading-relaxed text-muted-2">
              Validation humaine requise. Ouvre un espace Actions IA contextualisé — Préparer /
              Marquer / Ignorer, sans application automatique.
            </p>
          </>
        ) : (
          <p className="text-xs text-muted">Sélectionnez une alerte pour l’analyse IA.</p>
        )}
      </aside>
    </div>
  )
}
