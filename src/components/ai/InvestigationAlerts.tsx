import { useEffect, useMemo, useState } from "react"
import { Film, Map, Sparkles, Truck, Inbox } from "lucide-react"
import { useOpsStore } from "@/lib/store/useOpsStore"
import { useUiStore } from "@/lib/store/useUiStore"
import { useWorkspaceStore } from "@/lib/store/useWorkspaceStore"
import { investigationKey, useInvestigationStore } from "@/lib/store/useInvestigationStore"
import type { InvestigationTriggerInput } from "@/lib/api/types/ai"
import type { WorkspacePanelProps } from "@/components/workspace/WorkspaceHost"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { MiniTimelineStrip } from "@/components/equipment/MiniTimelineStrip"
import { InvestigationEvidence, InvestigationUncertainty } from "./InvestigationResultView"
import { AiBlock, Fact, Section } from "./InvestigationLayout"
import { CONFIDENCE_LABEL, investigationFailure, investigationStatus } from "@/lib/ai/investigationPresentation"
import { SEVERITY_CONFIG } from "@/lib/status"
import { cn } from "@/lib/utils"

/** Original three-column workspace; live data never passes through demo intelligence. */
export function InvestigationAlerts({ tab }: Partial<WorkspacePanelProps>) {
  const ops = useOpsStore()
  const openWorkspace = useWorkspaceStore((s) => s.openWorkspace)
  const patchTabContext = useWorkspaceStore((s) => s.patchTabContext)
  const openEquipmentDrawer = useUiStore((s) => s.openEquipmentDrawer)
  const [selectedId, setSelectedId] = useState<string | null>(tab?.context.alertId ?? null)
  const [severity, setSeverity] = useState("all")
  const [zone, setZone] = useState("all")
  const alerts = ops.alerts.filter((a) => (severity === "all" || a.severity === severity) && (zone === "all" || a.zoneId === zone))
  const selected = alerts.find((a) => a.id === selectedId) ?? alerts[0]
  const siteId = ops.sites.find((s) => s.id === ops.selectedSiteId)?.databaseId
  const shiftId = ops.shifts.find((s) => s.id === ops.selectedShiftId)?.databaseId
  const alertId = selected?.id
  const tabId = tab?.id
  const scope = useMemo(() => siteId && alertId ? { site_id: siteId, shift_id: shiftId, source_record_id: alertId } : null, [siteId, shiftId, alertId])
  const key = scope ? investigationKey(scope) : ""
  const entry = useInvestigationStore((s) => s.entries[key])
  const { lookup, start } = useInvestigationStore.getState()
  const result = entry?.result
  const conclusion = result?.conclusion
  const recommendation = result?.recommendation
  const equipment = ops.equipment.find((e) => e.id === selected?.equipmentId)
  const selectedZone = ops.zones.find((z) => z.id === selected?.zoneId)
  const confidence = conclusion ? CONFIDENCE_LABEL[conclusion.confidence] : "Non évalué"
  const cause = conclusion?.root_cause ?? conclusion?.summary ?? "Non évalué — analyse IA non disponible."
  const busy = entry?.phase === "running" || entry?.phase === "loading"
  const failure = entry?.error ?? investigationFailure(result?.error)
  const segs = useMemo(() => selected?.equipmentId
    ? ops.timelineSegments.filter((s) => s.equipmentId === selected.equipmentId).sort((a, b) => a.start - b.start).slice(-10)
    : [], [ops.timelineSegments, selected?.equipmentId])

  useEffect(() => { setSelectedId(tab?.context.alertId ?? null) }, [tab?.context.alertId])
  useEffect(() => { if (scope) void lookup(scope) }, [scope, lookup]) // Reads only; POST requires a click.
  useEffect(() => {
    if (tabId && alertId) patchTabContext(tabId, {
      alertId, investigationId: result?.investigation_id,
      equipmentId: selected?.equipmentId ?? undefined, equipmentCode: equipment?.code,
      zoneId: selected?.zoneId ?? undefined, zoneName: selectedZone?.name,
    })
  }, [tabId, alertId, result?.investigation_id, selected?.equipmentId, selected?.zoneId, equipment?.code, selectedZone?.name, patchTabContext])

  function investigate() {
    if (!scope || !selected) return
    const trigger: InvestigationTriggerInput = {
      ...scope, trigger_type: "OPERATIONAL_EVENT", trigger_source: "USER_INVESTIGATE", source: "alertes-ui",
      equipment_id: equipment?.databaseId, zone_id: selectedZone?.databaseId,
      occurred_at: new Date(selected.createdAt).toISOString(),
      severity: selected.severity === "critical" ? "CRITICAL" : selected.severity === "warning" ? "WARNING" : "INFO",
      payload: { category: selected.category, title: selected.title, description: selected.description },
    }
    void start(trigger)
  }
  const context = {
    alertId, equipmentId: selected?.equipmentId ?? undefined, equipmentCode: equipment?.code,
    zoneId: selected?.zoneId ?? undefined, zoneName: selectedZone?.name, investigationId: result?.investigation_id,
  }
  return <div className="flex h-full overflow-hidden">
    <aside aria-label="Liste des alertes" className="flex w-[28%] min-w-[260px] max-w-[360px] flex-col border-r border-border bg-surface">
      <div className="shrink-0 space-y-2 border-b border-border px-3 py-2.5">
        <div className="flex rounded-md bg-surface-2 p-0.5">
          <span className="flex h-7 flex-1 items-center justify-center gap-1 rounded-md bg-surface text-[11px] font-medium shadow-sm">En cours <span className="text-[10px] text-muted-2">{ops.alerts.length}</span></span>
          <button disabled title="Prédictions non disponibles en V1" className="h-7 flex-1 text-[11px] text-muted">Prédictions · —</button>
        </div>
        <div className="flex flex-wrap gap-1">
          {(["all", "critical", "warning", "info"] as const).map((f) => <button key={f} onClick={() => setSeverity(f)} className={cn("h-6 rounded-md px-2 text-[10px] font-medium", severity === f ? "bg-accent text-white" : "bg-surface-2 text-muted")}>{f === "all" ? "Tous" : SEVERITY_CONFIG[f].label}</button>)}
          <select aria-label="Zone" className="h-6 max-w-[110px] rounded-md border border-border bg-background px-1 text-[10px]" value={zone} onChange={(e) => setZone(e.target.value)}><option value="all">Zone</option>{ops.zones.map((z) => <option key={z.id} value={z.id}>{z.name}</option>)}</select>
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {!alerts.length && <div className="flex flex-col items-center gap-2 py-16 text-center"><Inbox className="size-5 text-muted-2" /><p className="text-xs text-muted">{ops.apiPollError ? "Alertes indisponibles." : !ops.apiBootstrapped ? "Chargement des alertes…" : "Aucune alerte."}</p></div>}
        {alerts.map((a) => <button key={a.id} onClick={() => setSelectedId(a.id)} className={cn("flex w-full flex-col gap-0.5 border-b border-border px-3 py-2.5 text-left", selected?.id === a.id ? "bg-accent-soft/50" : "hover:bg-surface-2/70")}>
          <div className="flex items-center gap-1.5 text-[10px]"><span className={cn("size-1.5 rounded-full", SEVERITY_CONFIG[a.severity].dot)} /><span className={cn("font-semibold", SEVERITY_CONFIG[a.severity].color)}>{SEVERITY_CONFIG[a.severity].label}</span><span className="text-muted-2">{a.category}</span><span className="ml-auto tabular-nums text-muted-2">{new Date(a.createdAt).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" })}</span></div>
          <p className="text-[12px] font-medium text-foreground">{a.title}</p><p className="line-clamp-1 text-[11px] text-muted">{a.description}</p><p className="mt-0.5 text-[10px] text-muted-2">{a.location ?? "Localisation indisponible"}</p>
        </button>)}
      </div>
    </aside>
    <main className="min-w-0 flex-1 overflow-y-auto border-r border-border bg-background p-4">
      {ops.apiPollError && <p role="alert" className="mb-3 text-xs text-danger">Données opérationnelles non actualisées.</p>}
      {selected ? <div className="mx-auto max-w-2xl space-y-4">
        <header><div className="mb-1 flex flex-wrap gap-1.5"><Badge className={cn(SEVERITY_CONFIG[selected.severity].bg, SEVERITY_CONFIG[selected.severity].color, "border-transparent")}>{SEVERITY_CONFIG[selected.severity].label}</Badge><Badge variant="outline">{selected.category}</Badge><Badge variant="outline">En cours</Badge></div><h2 className="text-[16px] font-semibold text-foreground">{selected.title}</h2></header>
        <Section title="Résumé"><p className="text-[12px] leading-relaxed text-muted">{selected.description}</p><dl className="mt-2 grid grid-cols-2 gap-2 text-[11px]"><Fact label="Où" value={selectedZone?.name ?? selected.location ?? "—"} /><Fact label="Depuis" value={new Date(selected.createdAt).toLocaleString("fr-FR")} /><Fact label="Équipement" value={equipment?.code ?? "—"} mono /><Fact label="Confiance" value={confidence} /></dl></Section>
        <Section title="Pourquoi"><p className="text-[12px] font-medium text-foreground">{conclusion?.summary ?? `${investigationStatus(entry)} — cause non évaluée.`}</p>
          {conclusion && !conclusion.reliable_root_cause && <p className="mt-2 text-[11px] text-muted">Conclusion non fiable : aucune cause racine établie.</p>}
          {result?.hypotheses.map((h) => <div key={h.hypothesis_id} className="mt-2 text-[11px]"><p>Hypothèse · {CONFIDENCE_LABEL[h.confidence]} : {h.statement}</p><p className="text-muted">{h.rationale}</p><p className="text-muted-2">Appuis : {h.supporting_evidence_ids.join(", ") || "Aucun"}</p>{h.contradictory_evidence_ids.length > 0 && <p className="text-muted-2">Contradictions : {h.contradictory_evidence_ids.join(", ")}</p>}</div>)}
          {result && <InvestigationUncertainty result={result} />}
        </Section>
        <Section title="Preuves / signaux">{result ? <InvestigationEvidence result={result} /> : <p className="text-[11px] text-muted">Aucune preuve IA collectée. Le signal opérationnel reste visible dans le résumé.</p>}
          {segs.length > 0 && <div className="mt-2"><p className="mb-1 text-[10px] font-semibold uppercase text-muted-2">Film récent</p><MiniTimelineStrip segments={segs} rangeStart={segs[0].start} rangeEnd={ops.simNowIso ? new Date(ops.simNowIso).getTime() : segs[segs.length - 1].end ?? segs[segs.length - 1].start} /></div>}
        </Section>
        <Section title="Impact"><p className="text-[12px] text-muted">Impact non quantifié</p><p className="mt-1 text-[11px] text-muted-2">Conséquences si ignoré : non évaluées.</p></Section>
        <Section title="Liens utiles"><div className="flex flex-col gap-1.5"><Button size="sm" variant="outline" className="justify-start" onClick={() => openWorkspace({ type: "map", context })}><Map className="size-3.5" />Ouvrir la Carte</Button><Button size="sm" variant="outline" className="justify-start" disabled={!equipment} onClick={() => openWorkspace({ type: "timeline", context })}><Film className="size-3.5" />Ouvrir le Film</Button><Button size="sm" variant="outline" className="justify-start" disabled={!equipment} onClick={() => equipment && openEquipmentDrawer(equipment.id)}><Truck className="size-3.5" />Ouvrir l’équipement</Button></div></Section>
      </div> : <p className="text-xs text-muted">Sélectionnez une alerte.</p>}
    </main>
    <aside aria-label="Panel IA" className="flex w-[28%] min-w-[240px] max-w-[340px] flex-col overflow-y-auto bg-surface p-4">
      {selected ? <><h3 className="text-[11px] font-semibold uppercase tracking-wide text-muted-2">Panel IA</h3><p role="status" aria-live="polite" className="mt-2 text-[11px] text-muted">{investigationStatus(entry)}</p>
        {failure && <p role="alert" className="mt-2 text-xs text-danger">{failure}</p>}
        <div className="mt-3 space-y-3"><AiBlock label="Cause probable" value={cause} /><AiBlock label="Confiance" value={confidence} /><AiBlock label="Impact estimé" value="Impact non quantifié" /><AiBlock label="Action immédiate suggérée" value={recommendation?.description ?? "Non évalué"} /></div>
        {recommendation ? <Button className="mt-4 w-full gap-1.5" onClick={() => openWorkspace({ type: "actions", context, investigationId: result!.investigation_id })}><Sparkles className="size-3.5" />Ouvrir Actions IA</Button>
          : <Button className="mt-4 w-full gap-1.5" disabled={!scope || !!result || busy || entry?.creationUncertain || !!ops.apiPollError} onClick={investigate}><Sparkles className="size-3.5" />{entry?.phase === "running" ? "Analyse IA en cours" : "Investiguer"}</Button>}
        <Button className="mt-2 w-full" size="sm" variant="outline" disabled={!scope || busy} onClick={() => scope && void lookup(scope, true)}>Actualiser le résultat</Button>
        {!scope && <p className="mt-2 text-xs text-muted">Identité opérationnelle indisponible.</p>}
        <p className="mt-2 text-[10px] leading-relaxed text-muted-2">Validation humaine requise. Aucune application automatique aux équipements ou aux affectations.</p>
        {result && <p className="mt-3 break-all text-[10px] text-muted-2">Investigation {result.investigation_id}<br />{result.provider} / {result.model}</p>}
      </> : <p className="text-xs text-muted">Sélectionnez une alerte pour l’analyse IA.</p>}
    </aside>
  </div>
}
