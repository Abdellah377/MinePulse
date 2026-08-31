import { useEffect, useMemo, useState } from "react"
import { AlertTriangle, MessageSquare, Sparkles } from "lucide-react"
import { useInvestigationStore } from "@/lib/store/useInvestigationStore"
import { useWorkspaceStore } from "@/lib/store/useWorkspaceStore"
import { useOpsStore } from "@/lib/store/useOpsStore"
import type { WorkspacePanelProps } from "@/components/workspace/WorkspaceHost"
import { InvestigationResultView } from "./InvestigationResultView"
import { Chip } from "./InvestigationLayout"
import { AiExplanationBlock, AiExplanationPanel, AiWhyButton } from "./AiExplanation"
import { CONFIDENCE_LABEL, DIAGNOSIS_STATUS_LABEL, investigationFailure, investigationStatus } from "@/lib/ai/investigationPresentation"
import { compactOperatorText, operatorText } from "@/lib/ai/investigationReport"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Textarea } from "@/components/ui/textarea"
import { cn } from "@/lib/utils"
import { aiApi } from "@/lib/api/ai"
import type { InvestigationResult, JsonValue } from "@/lib/api/types/ai"
import type {
  DiscussionThread,
  RecommendationDecisionType,
  RecommendationDecisionView,
  RejectionReasonCategory,
} from "@/lib/api/types/actionsIa"
import { DECISION_STATUS_LABEL, REJECTION_REASON_LABEL } from "@/lib/api/types/actionsIa"

const REASON_OPTIONS = Object.keys(REJECTION_REASON_LABEL) as RejectionReasonCategory[]

function roadImpact(result?: InvestigationResult) {
  const item = result?.evidence.find((entry) => entry.source_tool === "road_network_context" && entry.available)
  const value = item?.value
  if (!value || typeof value !== "object" || Array.isArray(value)) return null
  const paths = (value as { candidatePaths?: Array<Record<string, JsonValue>> }).candidatePaths
  const path = paths?.[0]
  if (!path) return null
  const distance = typeof path.totalDistanceKm === "number" ? path.totalDistanceKm : null
  const minutes = typeof path.estimatedTravelMinutes === "number" ? path.estimatedTravelMinutes : null
  if (distance == null && minutes == null) return null
  return { distance, minutes, roadIds: Array.isArray(path.roadIds) ? path.roadIds.map(String) : [] }
}

function formatWhen(value?: string | null) {
  if (!value) return null
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return null
  return date.toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" })
}

export function InvestigationActions({ tab }: Partial<WorkspacePanelProps>) {
  const id = tab?.context.investigationId ?? tab?.investigationId
  const entry = useInvestigationStore((s) => id ? s.entries[id] : undefined)
  const retrieve = useInvestigationStore((s) => s.retrieve)
  const openWorkspace = useWorkspaceStore((s) => s.openWorkspace)
  const activateTab = useWorkspaceStore((s) => s.activateTab)
  const alert = useOpsStore((s) => s.alerts.find((a) => a.id === tab?.context.alertId))
  const [decisionView, setDecisionView] = useState<RecommendationDecisionView | null>(null)
  const [thread, setThread] = useState<DiscussionThread | null>(null)
  const [whyOpen, setWhyOpen] = useState(false)
  const [discussOpen, setDiscussOpen] = useState(false)
  const [formMode, setFormMode] = useState<"REJECTED" | "MODIFIED" | null>(null)
  const [reasonCategory, setReasonCategory] = useState<RejectionReasonCategory>("CONTRAINTE_NON_CONNUE_PAR_IA")
  const [reasonText, setReasonText] = useState("")
  const [alternative, setAlternative] = useState("")
  const [actorLabel, setActorLabel] = useState("")
  const [draft, setDraft] = useState("")
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)

  useEffect(() => { if (id) void retrieve(id) }, [id, retrieve])
  useEffect(() => {
    if (!id) return
    let cancelled = false
    void Promise.all([aiApi.getDecision(id), aiApi.getDiscussion(id)]).then(([nextDecision, nextThread]) => {
      if (cancelled) return
      setDecisionView(nextDecision)
      setThread(nextThread)
    }).catch(() => {
      if (!cancelled) setActionError("Décision opérateur indisponible.")
    })
    return () => { cancelled = true }
  }, [id])

  const result = entry?.result
  const rec = result?.recommendation
  const confidence = result?.conclusion ? CONFIDENCE_LABEL[result.conclusion.confidence] : "Non évalué"
  const failure = entry?.error ?? investigationFailure(result?.error)
  const impact = useMemo(() => roadImpact(result), [result])
  const status = decisionView?.decision_type ?? "PENDING"
  const record = decisionView?.decision ?? null

  function backToAlert() {
    const existing = useWorkspaceStore.getState().tabs.find((t) => t.type === "alerts" && t.context.alertId === tab?.context.alertId)
    if (existing) activateTab(existing.id)
    else openWorkspace({ type: "alerts", context: { ...tab?.context, investigationId: id } })
  }

  async function saveDecision(type: Exclude<RecommendationDecisionType, "PENDING">) {
    if (!id) return
    if (type === "ACCEPTED" && typeof window !== "undefined" && !window.confirm("Confirmer l’acceptation de cette recommandation ? Aucune action opérationnelle ne sera exécutée.")) {
      return
    }
    setBusy(true)
    setActionError(null)
    try {
      const saved = await aiApi.putDecision(id, {
        decision_type: type,
        reason_category: type === "REJECTED" || type === "MODIFIED" ? reasonCategory : null,
        reason_text: type === "REJECTED" || type === "MODIFIED" ? reasonText || null : null,
        alternative_action: type === "REJECTED" || type === "MODIFIED" ? alternative || null : null,
        actor_label: actorLabel || null,
      })
      setDecisionView({ investigation_id: id, decision_type: saved.decision_type, decision: saved })
      setFormMode(null)
    } catch {
      setActionError("Enregistrement de la décision impossible.")
    } finally {
      setBusy(false)
    }
  }

  async function sendDiscussion() {
    if (!id || !draft.trim()) return
    setBusy(true)
    setActionError(null)
    try {
      const next = await aiApi.postDiscussion(id, { content: draft.trim(), actor_label: actorLabel || null, generate_reply: true })
      setThread(next)
      setDraft("")
    } catch {
      setActionError("La discussion IA n’a pas pu répondre.")
    } finally {
      setBusy(false)
    }
  }

  if (!id) return <div className="flex h-full flex-col items-center justify-center gap-3 p-8 text-center">
    <Sparkles className="size-8 text-muted-2" /><h2 className="text-[15px] font-semibold">Actions IA</h2><p className="max-w-md text-[12px] text-muted">Sélectionnez une alerte dans Alertes IA, puis ouvrez la recommandation de son investigation.</p><Button onClick={() => openWorkspace({ type: "alerts", title: "Alertes IA" })}>Ouvrir Alertes IA</Button>
  </div>

  return <div className="flex h-full flex-col overflow-hidden">
    <header className="shrink-0 border-b border-border bg-surface px-4 py-3">
      <div className="flex flex-wrap items-start justify-between gap-3"><div className="min-w-0"><p className="text-[10px] font-semibold uppercase tracking-wide text-muted-2">Actions IA · contexte hérité</p><h1 className="mt-0.5 text-[15px] font-semibold text-foreground">{alert?.title ?? "Plan d’action"}</h1><p className="mt-1 max-w-2xl text-[12px] text-muted">{result?.conclusion?.summary ? operatorText(result.conclusion.summary) : investigationStatus(entry)}</p></div><Badge variant="outline" className="shrink-0">Confiance {confidence}</Badge></div>
      <div className="mt-3 flex flex-wrap gap-1.5"><Chip>Pourquoi : {result?.conclusion ? `${DIAGNOSIS_STATUS_LABEL[result.conclusion.diagnosis_status]}${result.conclusion.root_cause ? ` — ${compactOperatorText(result.conclusion.root_cause, 80)}` : ""}` : "Cause non déterminée"}</Chip><Chip>{investigationStatus(entry)}</Chip><Chip>Investigation {id}</Chip></div>
      <div className="mt-2 flex gap-2"><Button size="sm" variant="outline" onClick={backToAlert}>Retour aux alertes</Button><Button size="sm" variant="outline" disabled={entry?.phase === "loading"} onClick={() => void retrieve(id, true)}>Actualiser</Button></div>
      {failure && <p role="alert" className="mt-2 text-xs text-danger">{failure}</p>}
      {actionError && <p role="alert" className="mt-2 text-xs text-danger">{actionError}</p>}
    </header>
    <div className="grid min-h-0 flex-1 gap-3 overflow-hidden p-4 lg:grid-cols-12">
      <main className="flex min-h-0 flex-col gap-2 overflow-y-auto lg:col-span-7">
        <h2 className="text-[12px] font-semibold text-foreground">Recommandation IA</h2>
        {rec ? <article className={cn("rounded-md border px-3.5 py-3", status === "ACCEPTED" || status === "RESOLVED" ? "border-success/30 bg-success/5" : "border-border bg-surface")}>
          <div className="flex flex-wrap items-center gap-1.5"><Badge variant="outline" className="text-[10px]">Recommandation consultative</Badge><Badge variant="outline">{DECISION_STATUS_LABEL[status]}</Badge><span className="ml-auto text-[10px] text-muted-2">Confiance {confidence}</span></div>
          <h3 className="mt-1.5 text-[13px] font-semibold text-foreground">{operatorText(rec.description)}</h3>
          <p className="mt-1 text-[11px] text-muted"><span className="font-medium text-foreground">Pourquoi :</span> {operatorText(rec.rationale)}</p>
          <ul className="mt-2 list-inside list-disc text-[11px] text-muted">{rec.operational_constraints.map((c, i) => <li key={i}>{operatorText(c)}</li>)}</ul>
          {impact ? <p className="mt-2 text-[11px] text-muted">Impact attendu (preuves routières) : {impact.distance != null ? `${impact.distance} km` : "distance inconnue"}{impact.minutes != null ? ` · ${impact.minutes} min` : ""}{impact.roadIds.length ? ` · ${impact.roadIds.join(" → ")}` : ""}</p> : <p className="mt-2 text-[11px] text-muted">Impact non quantifié</p>}
          <div className="mt-2.5"><AiWhyButton expanded={whyOpen} onClick={() => setWhyOpen((open) => !open)} /></div>
          <AiExplanationPanel open={whyOpen}>
            <AiExplanationBlock label="Action recommandée">{operatorText(rec.description)}</AiExplanationBlock>
            <AiExplanationBlock label="Conclusion">{result?.conclusion?.summary ? operatorText(result.conclusion.summary) : "Non disponible"}</AiExplanationBlock>
            {result && <InvestigationResultView result={result} />}
          </AiExplanationPanel>
          {status === "PENDING" && !formMode && (
            <div className="mt-3 border-t border-border pt-3">
              <p className="text-[11px] font-semibold text-foreground">Votre décision</p>
              <div className="mt-2 flex flex-wrap gap-1.5">
                <Button size="sm" onClick={() => void saveDecision("ACCEPTED")} disabled={busy}>Accepter</Button>
                <Button size="sm" variant="outline" onClick={() => setFormMode("MODIFIED")}>Modifier</Button>
                <Button size="sm" variant="ghost" onClick={() => setFormMode("REJECTED")}>Rejeter</Button>
              </div>
            </div>
          )}
          {formMode && (
            <form className="mt-3 space-y-2 border-t border-border pt-3" onSubmit={(event) => { event.preventDefault(); void saveDecision(formMode) }}>
              <p className="text-[11px] font-semibold">{formMode === "REJECTED" ? "Pourquoi rejetez-vous cette recommandation ?" : "Quelle action souhaitez-vous à la place ?"}</p>
              <label className="block text-[11px] text-muted">Motif
                <select className="mt-1 h-8 w-full rounded-md border border-border bg-surface-2 px-2 text-xs" value={reasonCategory} onChange={(event) => setReasonCategory(event.target.value as RejectionReasonCategory)}>
                  {REASON_OPTIONS.map((key) => <option key={key} value={key}>{REJECTION_REASON_LABEL[key]}</option>)}
                </select>
              </label>
              <label className="block text-[11px] text-muted">Commentaire
                <Textarea value={reasonText} onChange={(event) => setReasonText(event.target.value)} rows={3} />
              </label>
              <label className="block text-[11px] text-muted">Alternative
                <Textarea value={alternative} onChange={(event) => setAlternative(event.target.value)} rows={2} />
              </label>
              <label className="block text-[11px] text-muted">Acteur (facultatif)
                <input className="mt-1 h-8 w-full rounded-md border border-border bg-surface-2 px-2 text-xs" value={actorLabel} onChange={(event) => setActorLabel(event.target.value)} />
              </label>
              <div className="flex gap-1.5"><Button size="sm" type="submit" disabled={busy}>Enregistrer</Button><Button size="sm" type="button" variant="ghost" onClick={() => setFormMode(null)}>Annuler</Button></div>
            </form>
          )}
          {record && status !== "PENDING" && (
            <div className="mt-3 border-t border-border pt-3 text-[11px] text-muted">
              <p className="font-semibold text-foreground">{DECISION_STATUS_LABEL[status]}</p>
              <p className="mt-1">{formatWhen(record.updated_at)}{record.actor_label ? ` · ${record.actor_label}` : ""}</p>
              {record.reason_text && <p className="mt-1">{record.reason_text}</p>}
              {status !== "RESOLVED" && <Button className="mt-2" size="sm" variant="outline" disabled={busy} onClick={() => void saveDecision("RESOLVED")}>Clôturer</Button>}
            </div>
          )}
        </article> : <p className="py-8 text-center text-xs text-muted">Recommandation non évaluée ou indisponible.</p>}
      </main>
      <aside className="flex min-h-0 flex-col gap-3 overflow-y-auto lg:col-span-5">
        <div className="rounded-md border border-border bg-surface p-3">
          <h3 className="text-[12px] font-semibold text-foreground">Discussion de la recommandation</h3>
          <p className="mt-1 text-[11px] text-muted">Hors investigation. L’envoi d’un message est le seul appel IA de cet écran.</p>
          <Button className="mt-2" size="sm" variant="outline" onClick={() => setDiscussOpen((open) => !open)}><MessageSquare className="size-3.5" />Discuter cette recommandation</Button>
          {discussOpen && (
            <div className="mt-3 space-y-2" data-testid="recommendation-discussion">
              <div className="max-h-48 space-y-2 overflow-y-auto rounded-md border border-border bg-background p-2">
                {(thread?.messages ?? []).length === 0 && <p className="text-[11px] text-muted">Aucun échange pour l’instant.</p>}
                {(thread?.messages ?? []).map((message) => (
                  <div key={message.message_id} className="text-[11px]"><p className="font-semibold text-foreground/80">{message.role === "OPERATOR" ? "Opérateur" : "MinePulse"}</p><p className="text-muted">{message.content}</p></div>
                ))}
              </div>
              <Textarea value={draft} onChange={(event) => setDraft(event.target.value)} rows={3} placeholder="Question sur cette recommandation…" />
              <Button size="sm" disabled={busy || !draft.trim()} onClick={() => void sendDiscussion()}>Envoyer</Button>
            </div>
          )}
        </div>
        <div className="rounded-md border border-border bg-surface p-3"><h3 className="text-[12px] font-semibold text-foreground">Simulation / comparaison</h3><p className="mt-2 flex items-start gap-2 text-[11px] text-muted"><AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-muted-2" />Aucune exécution opérationnelle. Acceptation ≠ application FMS.</p></div>
        <div className="rounded-md border border-border bg-surface p-3 text-[11px] text-muted"><p className="font-semibold text-foreground/80">Rappel</p><p className="mt-1">Accepter, modifier ou rejeter enregistre une décision opérateur. MinePulse n’exécute pas le reroutage, n’ouvre pas les routes et ne crée pas d’ordre de travail.</p></div>
      </aside>
    </div>
  </div>
}
