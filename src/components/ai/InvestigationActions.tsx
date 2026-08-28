import { useEffect, useState } from "react"
import { AlertTriangle, Bookmark, Flag, Sparkles } from "lucide-react"
import { useInvestigationStore } from "@/lib/store/useInvestigationStore"
import { useWorkspaceStore } from "@/lib/store/useWorkspaceStore"
import { useOpsStore } from "@/lib/store/useOpsStore"
import type { WorkspacePanelProps } from "@/components/workspace/WorkspaceHost"
import { InvestigationResultView } from "./InvestigationResultView"
import { InvestigationDebugPanel } from "./InvestigationDebugPanel"
import { Chip } from "./InvestigationLayout"
import { CONFIDENCE_LABEL, DIAGNOSIS_STATUS_LABEL, investigationFailure, investigationStatus } from "@/lib/ai/investigationPresentation"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"

export function InvestigationActions({ tab }: Partial<WorkspacePanelProps>) {
  const id = tab?.context.investigationId ?? tab?.investigationId
  const entry = useInvestigationStore((s) => id ? s.entries[id] : undefined)
  const retrieve = useInvestigationStore((s) => s.retrieve)
  const openWorkspace = useWorkspaceStore((s) => s.openWorkspace)
  const activateTab = useWorkspaceStore((s) => s.activateTab)
  const setTabState = useWorkspaceStore((s) => s.setTabState)
  const savedDecision = useWorkspaceStore((s) => tab?.id ? s.tabState[tab.id]?.reviewDecision : undefined)
  const alert = useOpsStore((s) => s.alerts.find((a) => a.id === tab?.context.alertId))
  const [localDecision, setLocalDecision] = useState("pending")
  const decision = typeof savedDecision === "string" ? savedDecision : localDecision
  useEffect(() => { if (id) void retrieve(id) }, [id, retrieve])
  const result = entry?.result
  const rec = result?.recommendation
  const confidence = result?.conclusion ? CONFIDENCE_LABEL[result.conclusion.confidence] : "Non évalué"
  const failure = entry?.error ?? investigationFailure(result?.error)
  function mark(value: string) {
    setLocalDecision(value)
    if (tab?.id) setTabState(tab.id, { reviewDecision: value })
  }
  function backToAlert() {
    // Reuse the originating alert workspace even if its context has more fields.
    const existing = useWorkspaceStore.getState().tabs.find((t) => t.type === "alerts" && t.context.alertId === tab?.context.alertId)
    if (existing) activateTab(existing.id)
    else openWorkspace({ type: "alerts", context: { ...tab?.context, investigationId: id } })
  }
  if (!id) return <div className="flex h-full flex-col items-center justify-center gap-3 p-8 text-center">
    <Sparkles className="size-8 text-muted-2" /><h2 className="text-[15px] font-semibold">Actions IA</h2><p className="max-w-md text-[12px] text-muted">Sélectionnez une alerte dans Alertes IA, puis ouvrez la recommandation de son investigation.</p><Button onClick={() => openWorkspace({ type: "alerts", title: "Alertes IA" })}>Ouvrir Alertes IA</Button>
  </div>
  return <div className="flex h-full flex-col overflow-hidden">
    <header className="shrink-0 border-b border-border bg-surface px-4 py-3">
      <div className="flex flex-wrap items-start justify-between gap-3"><div className="min-w-0"><p className="text-[10px] font-semibold uppercase tracking-wide text-muted-2">Actions IA · contexte hérité</p><h1 className="mt-0.5 text-[15px] font-semibold text-foreground">{alert?.title ?? "Plan d’action"}</h1><p className="mt-1 max-w-2xl text-[12px] text-muted">{result?.conclusion?.summary ?? investigationStatus(entry)}</p></div><Badge variant="outline" className="shrink-0">Confiance {confidence}</Badge></div>
      <div className="mt-3 flex flex-wrap gap-1.5"><Chip>Pourquoi : {result?.conclusion ? `${DIAGNOSIS_STATUS_LABEL[result.conclusion.diagnosis_status]}${result.conclusion.root_cause ? ` — ${result.conclusion.root_cause}` : ""}` : "Cause non déterminée"}</Chip><Chip>{investigationStatus(entry)}</Chip><Chip>Investigation {id}</Chip></div>
      <div className="mt-2 flex gap-2"><Button size="sm" variant="outline" onClick={backToAlert}>Retour aux alertes</Button><Button size="sm" variant="outline" disabled={entry?.phase === "loading"} onClick={() => void retrieve(id, true)}>Actualiser</Button></div>
      {failure && <p role="alert" className="mt-2 text-xs text-danger">{failure}</p>}
    </header>
    <div className="grid min-h-0 flex-1 gap-3 overflow-hidden p-4 lg:grid-cols-12">
      <main className="flex min-h-0 flex-col gap-2 overflow-y-auto lg:col-span-7">
        <h2 className="text-[12px] font-semibold text-foreground">Recommandations ({rec ? 1 : 0})</h2>
        {rec ? <article className={cn("rounded-md border px-3.5 py-3", decision === "prepared" || decision === "marked" ? "border-success/30 bg-success/5" : "border-border bg-surface")}>
          <div className="flex flex-wrap items-center gap-1.5"><Badge variant="outline" className="text-[10px]">Recommandation consultative</Badge>{decision !== "pending" && <Badge variant="outline">{decision === "prepared" ? "Préparé" : decision === "marked" ? "Marqué" : "Ignoré"} · local</Badge>}<span className="ml-auto text-[10px] text-muted-2">Confiance {confidence}</span></div>
          <h3 className="mt-1.5 text-[13px] font-semibold text-foreground">{rec.description}</h3><p className="mt-1 text-[11px] text-muted">{rec.rationale}</p>
          <ul className="mt-2 list-inside list-disc text-[11px] text-muted">{rec.operational_constraints.map((c, i) => <li key={i}>{c}</li>)}</ul>
          <p className="mt-2 text-[11px] text-muted">Preuves : {rec.evidence_ids.join(", ") || "Aucune"}</p><p className="mt-2 text-[11px] text-muted">Impact non quantifié</p>
          <div className="mt-2.5 flex flex-wrap gap-1.5"><Button size="sm" variant="outline" disabled title="Simulation d’impact non disponible en V1">Simuler</Button><Button size="sm" variant="outline" onClick={() => mark("prepared")}><Flag className="size-3.5" />Préparer</Button><Button size="sm" variant="outline" onClick={() => mark("marked")}><Bookmark className="size-3.5" />Marquer</Button><Button size="sm" variant="ghost" onClick={() => mark(decision === "dismissed" ? "pending" : "dismissed")}>{decision === "dismissed" ? "Rétablir" : "Ignorer"}</Button></div>
        </article> : <p className="py-8 text-center text-xs text-muted">Recommandation non évaluée ou indisponible.</p>}
        {result && <details className="rounded-md border border-border bg-surface p-3"><summary className="cursor-pointer text-[12px] font-semibold">Conclusion / preuves de l’investigation</summary><div className="mt-3"><InvestigationResultView result={result} /><InvestigationDebugPanel investigationId={result.investigation_id} /></div></details>}
      </main>
      <aside className="flex min-h-0 flex-col gap-3 overflow-y-auto lg:col-span-5">
        <div className="rounded-md border border-border bg-surface p-3"><h3 className="text-[12px] font-semibold text-foreground">Simulation / comparaison</h3><p className="mt-2 flex items-start gap-2 text-[11px] text-muted"><AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-muted-2" />Simulation d’impact non disponible en V1</p><p className="mt-2 text-[11px] text-muted">Gain de production, réduction d’attente, amélioration de cycle : non évalués.</p></div>
        <div className="rounded-md border border-border bg-surface p-3 text-[11px] text-muted"><p className="font-semibold text-foreground/80">Rappel</p><p className="mt-1">Préparer · Marquer · Ignorer — notes locales de revue, conservées dans cet espace pendant la session. Aucune validation serveur ni application au FMS.</p><p className="mt-2">Validation humaine requise. Les actions restent sous contrôle du chef de poste.</p></div>
      </aside>
    </div>
  </div>
}
