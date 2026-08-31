import { useEffect, useMemo, useState } from "react"
import { AlertTriangle, MessageSquare } from "lucide-react"
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
import { DECISION_STATUS_LABEL, FOLLOW_UP_STATUS_LABEL, REJECTION_REASON_LABEL } from "@/lib/api/types/actionsIa"
import type { ActionsInboxItem, OptimizationCandidate, OptimizationRun } from "@/lib/api/types/optimization"
import { SEVERITY_CONFIG } from "@/lib/status"
import { operationalAlertTime } from "@/lib/alerts/order"
import { timeAgo } from "@/lib/format"

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

function opsCtx() {
  const ops = useOpsStore.getState()
  return { siteCode: ops.selectedSiteId, shiftId: ops.selectedShiftId }
}

export function InvestigationActions({ tab }: Partial<WorkspacePanelProps>) {
  const investigationId = tab?.context.investigationId ?? tab?.investigationId
  const contextAlertId = tab?.context.alertId as string | undefined
  const entry = useInvestigationStore((s) => investigationId ? s.entries[investigationId] : undefined)
  const retrieve = useInvestigationStore((s) => s.retrieve)
  const openWorkspace = useWorkspaceStore((s) => s.openWorkspace)
  const activateTab = useWorkspaceStore((s) => s.activateTab)
  const updateAlertStatus = useOpsStore((s) => s.updateAlertStatus)
  const [inbox, setInbox] = useState<ActionsInboxItem[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(contextAlertId ?? null)
  const [run, setRun] = useState<OptimizationRun | null>(null)
  const [decisionView, setDecisionView] = useState<RecommendationDecisionView | null>(null)
  const [thread, setThread] = useState<DiscussionThread | null>(null)
  const [whyOpen, setWhyOpen] = useState(false)
  const [optWhyOpen, setOptWhyOpen] = useState(false)
  const [discussOpen, setDiscussOpen] = useState(false)
  const [formMode, setFormMode] = useState<"REJECTED" | "MODIFIED" | null>(null)
  const [reasonCategory, setReasonCategory] = useState<RejectionReasonCategory>("CONTRAINTE_NON_CONNUE_PAR_IA")
  const [reasonText, setReasonText] = useState("")
  const [alternative, setAlternative] = useState("")
  const [actorLabel, setActorLabel] = useState("")
  const [draft, setDraft] = useState("")
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)

  const selected = inbox.find((row) => row.id === selectedId) ?? inbox[0]
  const alertId = selected?.id ?? contextAlertId ?? null
  const id = selected?.investigationId ?? investigationId

  useEffect(() => {
    let cancelled = false
    void aiApi.listInbox({ limit: 20 }, opsCtx()).then((page) => {
      if (cancelled) return
      setInbox(page.items)
      setSelectedId((current) => current ?? contextAlertId ?? page.items[0]?.id ?? null)
    }).catch(() => {
      if (!cancelled) setActionError("File Actions IA indisponible.")
    })
    return () => { cancelled = true }
  }, [contextAlertId])

  useEffect(() => {
    if (contextAlertId) setSelectedId(contextAlertId)
  }, [contextAlertId])

  useEffect(() => { if (id) void retrieve(id) }, [id, retrieve])
  useEffect(() => {
    if (!alertId) return
    let cancelled = false
    void aiApi.getInboxDetail(alertId, opsCtx()).then((detail) => {
      if (cancelled) return
      if (detail.latestRun) {
        setRun({
          runId: detail.latestRun.runId,
          alertId,
          siteId: 0,
          optimizerVersion: detail.latestRun.optimizerVersion,
          weights: {},
          eligibility: detail.latestRun.eligibility,
          outcome: detail.latestRun.outcome,
          snapshotDigest: null,
          candidates: detail.latestRun.candidates,
          recommendedCandidateId: detail.latestRun.recommendedCandidateId,
          weatherStatus: detail.latestRun.weatherStatus,
          createdAt: detail.latestRun.createdAt,
          explanation: detail.latestRun.explanation,
        })
      } else {
        setRun(null)
      }
      if (detail.decision) {
        setDecisionView({
          investigation_id: detail.decision.investigation_id,
          decision_type: detail.decision.decision_type,
          follow_up_status: detail.decision.follow_up_status,
          decision: detail.decision,
        })
      }
    }).catch(() => undefined)
    return () => { cancelled = true }
  }, [alertId])

  useEffect(() => {
    if (!id) return
    let cancelled = false
    void Promise.all([aiApi.getDecision(id), aiApi.getDiscussion(id)]).then(([nextDecision, nextThread]) => {
      if (cancelled) return
      setDecisionView(nextDecision)
      setThread(nextThread)
    }).catch(() => undefined)
    return () => { cancelled = true }
  }, [id])

  const result = entry?.result
  const rec = result?.recommendation
  const confidence = result?.conclusion ? CONFIDENCE_LABEL[result.conclusion.confidence] : "Non évalué"
  const failure = entry?.error ?? investigationFailure(result?.error)
  const impact = useMemo(() => roadImpact(result), [result])
  const status = decisionView?.decision_type ?? "PENDING"
  const record = decisionView?.decision ?? null
  const followUp = record?.follow_up_status ?? decisionView?.follow_up_status ?? null
  const eligible = selected?.optimizationEligible ?? false
  const handled = selected?.status === "resolved"
  const hasPlan = Boolean(rec || (run && run.candidates.length))

  function backToAlert() {
    const existing = useWorkspaceStore.getState().tabs.find((t) => t.type === "alerts" && t.context.alertId === alertId)
    if (existing) activateTab(existing.id)
    else openWorkspace({ type: "alerts", context: { ...tab?.context, alertId: alertId ?? undefined, investigationId: id } })
  }

  async function saveDecision(type: Exclude<RecommendationDecisionType, "PENDING">) {
    if (type === "ACCEPTED" && typeof window !== "undefined" && !window.confirm("Confirmer l’acceptation de cette recommandation ? Aucune action opérationnelle ne sera exécutée.")) {
      return
    }
    setBusy(true)
    setActionError(null)
    try {
      const body = {
        decision_type: type,
        reason_category: type === "REJECTED" || type === "MODIFIED" ? reasonCategory : null,
        reason_text: type === "REJECTED" || type === "MODIFIED" ? reasonText || null : null,
        alternative_action: type === "REJECTED" || type === "MODIFIED" ? alternative || null : null,
        actor_label: actorLabel || null,
      }
      const saved = alertId
        ? await aiApi.putInboxDecision(alertId, body, opsCtx())
        : id
          ? await aiApi.putDecision(id, body)
          : null
      if (!saved) return
      setDecisionView({
        investigation_id: saved.investigation_id,
        decision_type: saved.decision_type,
        follow_up_status: saved.follow_up_status,
        decision: saved,
      })
      setFormMode(null)
    } catch {
      setActionError("Enregistrement de la décision impossible.")
    } finally {
      setBusy(false)
    }
  }

  async function closeFollowUp() {
    if (!id) return
    setBusy(true)
    setActionError(null)
    try {
      const saved = await aiApi.patchFollowUp(id, { follow_up_status: "RESOLVED" })
      setDecisionView({ investigation_id: id, decision_type: saved.decision_type, follow_up_status: saved.follow_up_status, decision: saved })
    } catch {
      setActionError("Clôture du suivi impossible.")
    } finally {
      setBusy(false)
    }
  }

  async function markHandled() {
    if (!alertId) return
    setBusy(true)
    setActionError(null)
    try {
      updateAlertStatus(alertId, "resolved", actorLabel || "Chef de poste")
      setInbox((rows) => rows.filter((row) => row.id !== alertId))
      setSelectedId((current) => (current === alertId ? inbox.find((row) => row.id !== alertId)?.id ?? null : current))
    } catch {
      setActionError("Impossible de marquer le dossier comme traité.")
    } finally {
      setBusy(false)
    }
  }

  async function runOptimize() {
    if (!alertId) return
    setBusy(true)
    setActionError(null)
    try {
      const next = await aiApi.createOptimizationRun(alertId, opsCtx())
      setRun(next)
      setInbox((rows) => rows.map((row) => row.id === alertId ? { ...row, latestRunOutcome: next.outcome, optimizationEligible: next.eligibility === "OPTIMIZABLE" } : row))
    } catch {
      setActionError("Optimisation de dispatch indisponible.")
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

  return (
    <div className="flex h-full overflow-hidden">
      <aside aria-label="File Actions IA" className="flex w-[32%] min-w-[240px] max-w-[380px] flex-col border-r border-border bg-surface lg:w-1/3">
        <div className="shrink-0 border-b border-border px-3 py-2.5">
          <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-2">Actions IA</p>
          <p className="text-[12px] text-muted">{inbox.length} dossier{inbox.length > 1 ? "s" : ""} ouvert{inbox.length > 1 ? "s" : ""}</p>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto">
          {!inbox.length && (
            <p className="px-3 py-8 text-center text-[12px] text-muted">Aucun dossier non traité.</p>
          )}
          {inbox.map((row) => {
            const active = (selected?.id ?? selectedId) === row.id
            return (
              <button
                key={row.id}
                type="button"
                onClick={() => setSelectedId(row.id)}
                className={cn("flex w-full flex-col gap-0.5 border-b border-border px-3 py-2.5 text-left", active ? "bg-accent-soft/50" : "hover:bg-surface-2/70")}
              >
                <div className="flex items-center gap-1.5 text-[10px]">
                  <span className={cn("size-1.5 rounded-full", SEVERITY_CONFIG[row.severity].dot)} />
                  <span className={cn("font-semibold", SEVERITY_CONFIG[row.severity].color)}>{SEVERITY_CONFIG[row.severity].label}</span>
                  <span className="ml-auto tabular-nums text-muted-2">{timeAgo(operationalAlertTime(row))}</span>
                </div>
                <p className="text-[12px] font-medium text-foreground">{row.title}</p>
                <p className="text-[10px] text-muted-2">{row.equipmentId ?? row.zoneId ?? row.location} · {row.hasInvestigation ? "Investigation" : "Sans investigation"} · {row.optimizationEligible ? "Optimisable" : "Dispatch N/A"}</p>
              </button>
            )
          })}
        </div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <header className="shrink-0 border-b border-border bg-surface px-4 py-3">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-2">Dossier alerte</p>
              <h1 className="mt-0.5 text-[15px] font-semibold text-foreground">{selected?.title ?? "Actions IA"}</h1>
              <p className="mt-1 max-w-2xl text-[12px] text-muted">{selected?.description ?? (result?.conclusion?.summary ? operatorText(result.conclusion.summary) : "Sélectionnez un dossier. Aucun appel IA à l’ouverture.")}</p>
            </div>
            <Badge variant="outline" className="shrink-0">Confiance {confidence}</Badge>
          </div>
          <div className="mt-3 flex flex-wrap gap-1.5">
            <Chip>Pourquoi : {result?.conclusion ? `${DIAGNOSIS_STATUS_LABEL[result.conclusion.diagnosis_status]}${result.conclusion.root_cause ? ` — ${compactOperatorText(result.conclusion.root_cause, 80)}` : ""}` : "Cause non déterminée"}</Chip>
            {id && <Chip>{investigationStatus(entry)}</Chip>}
            {id && <Chip>Investigation {id}</Chip>}
          </div>
          <div className="mt-2 flex flex-wrap gap-2">
            <Button size="sm" variant="outline" onClick={backToAlert}>Retour aux alertes</Button>
            {id && <Button size="sm" variant="outline" disabled={entry?.phase === "loading"} onClick={() => void retrieve(id, true)}>Actualiser</Button>}
            <Button size="sm" disabled={!alertId || handled || busy} onClick={() => void markHandled()}>Marquer comme traité</Button>
          </div>
          {failure && <p role="alert" className="mt-2 text-xs text-danger">{failure}</p>}
          {actionError && <p role="alert" className="mt-2 text-xs text-danger">{actionError}</p>}
        </header>
        <div className="grid min-h-0 flex-1 gap-3 overflow-hidden p-4 lg:grid-cols-12">
          <main className="flex min-h-0 flex-col gap-2 overflow-y-auto lg:col-span-7">
            {selected && (
              <section className="rounded-md border border-border bg-surface px-3.5 py-3">
                <h2 className="text-[12px] font-semibold text-foreground">Ce qui s’est passé</h2>
                <p className="mt-1 text-[11px] text-muted">{operatorText(selected.description)}</p>
              </section>
            )}
            <h2 className="text-[12px] font-semibold text-foreground">Recommandation IA</h2>
            {rec ? (
              <article className={cn("rounded-md border px-3.5 py-3", status === "ACCEPTED" ? "border-success/30 bg-success/5" : "border-border bg-surface")}>
                <div className="flex flex-wrap items-center gap-1.5">
                  <Badge variant="outline" className="text-[10px]">Recommandation consultative</Badge>
                  <Badge variant="outline">{DECISION_STATUS_LABEL[status]}</Badge>
                  {followUp && <Badge variant="outline">{FOLLOW_UP_STATUS_LABEL[followUp]}</Badge>}
                  <span className="ml-auto text-[10px] text-muted-2">Confiance {confidence}</span>
                </div>
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
                <DecisionControls
                  status={status}
                  formMode={formMode}
                  setFormMode={setFormMode}
                  busy={busy}
                  saveDecision={saveDecision}
                  reasonCategory={reasonCategory}
                  setReasonCategory={setReasonCategory}
                  reasonText={reasonText}
                  setReasonText={setReasonText}
                  alternative={alternative}
                  setAlternative={setAlternative}
                  actorLabel={actorLabel}
                  setActorLabel={setActorLabel}
                  record={record}
                  followUp={followUp}
                  closeFollowUp={closeFollowUp}
                />
              </article>
            ) : (
              <p className="py-4 text-center text-xs text-muted">Recommandation non évaluée ou indisponible. L’investigation n’est pas requise pour optimiser le dispatch.</p>
            )}
            <section className="rounded-md border border-border bg-surface px-3.5 py-3">
              <div className="flex items-center justify-between gap-2">
                <h2 className="text-[12px] font-semibold text-foreground">Optimisation de dispatch</h2>
                {eligible ? (
                  <Button size="sm" disabled={!alertId || busy} onClick={() => void runOptimize()}>Optimiser</Button>
                ) : (
                  <span className="text-[10px] text-muted-2">Optimisation de dispatch non applicable</span>
                )}
              </div>
              {run && <OptimizationPlans run={run} whyOpen={optWhyOpen} onToggleWhy={() => setOptWhyOpen((open) => !open)} />}
              {!eligible && <p className="mt-2 text-[11px] text-muted">Optimisation de dispatch non applicable pour ce type d’alerte.</p>}
              {hasPlan && status === "PENDING" && !rec && (
                <div className="mt-3 border-t border-border pt-3">
                  <DecisionControls
                    status={status}
                    formMode={formMode}
                    setFormMode={setFormMode}
                    busy={busy}
                    saveDecision={saveDecision}
                    reasonCategory={reasonCategory}
                    setReasonCategory={setReasonCategory}
                    reasonText={reasonText}
                    setReasonText={setReasonText}
                    alternative={alternative}
                    setAlternative={setAlternative}
                    actorLabel={actorLabel}
                    setActorLabel={setActorLabel}
                    record={record}
                    followUp={followUp}
                    closeFollowUp={closeFollowUp}
                  />
                </div>
              )}
            </section>
          </main>
          <aside className="flex min-h-0 flex-col gap-3 overflow-y-auto lg:col-span-5">
            <div className="rounded-md border border-border bg-surface p-3">
              <h3 className="text-[12px] font-semibold text-foreground">Discussion de la recommandation</h3>
              <p className="mt-1 text-[11px] text-muted">Hors investigation. L’envoi d’un message est le seul appel IA de cet écran.</p>
              <Button className="mt-2" size="sm" variant="outline" disabled={!id} onClick={() => setDiscussOpen((open) => !open)}><MessageSquare className="size-3.5" />Discuter cette recommandation</Button>
              {discussOpen && id && (
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
            <div className="rounded-md border border-border bg-surface p-3 text-[11px] text-muted"><p className="font-semibold text-foreground/80">Rappel</p><p className="mt-1">Accepter, modifier ou rejeter enregistre une décision opérateur. « Marquer comme traité » clôt le dossier alerte. MinePulse n’exécute pas le reroutage, n’ouvre pas les routes et ne crée pas d’ordre de travail.</p></div>
          </aside>
        </div>
      </div>
    </div>
  )
}

function DecisionControls({
  status, formMode, setFormMode, busy, saveDecision, reasonCategory, setReasonCategory, reasonText, setReasonText, alternative, setAlternative, actorLabel, setActorLabel, record, followUp, closeFollowUp,
}: {
  status: RecommendationDecisionType
  formMode: "REJECTED" | "MODIFIED" | null
  setFormMode: (mode: "REJECTED" | "MODIFIED" | null) => void
  busy: boolean
  saveDecision: (type: Exclude<RecommendationDecisionType, "PENDING">) => void
  reasonCategory: RejectionReasonCategory
  setReasonCategory: (value: RejectionReasonCategory) => void
  reasonText: string
  setReasonText: (value: string) => void
  alternative: string
  setAlternative: (value: string) => void
  actorLabel: string
  setActorLabel: (value: string) => void
  record: RecommendationDecisionView["decision"]
  followUp: string | null
  closeFollowUp: () => void
}) {
  return (
    <>
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
          {followUp && <p className="mt-1">{FOLLOW_UP_STATUS_LABEL[followUp]}</p>}
          <p className="mt-1">{formatWhen(record.updated_at)}{record.actor_label ? ` · ${record.actor_label}` : ""}</p>
          {record.reason_text && <p className="mt-1">{record.reason_text}</p>}
          {followUp !== "RESOLVED" && <Button className="mt-2" size="sm" variant="outline" disabled={busy} onClick={() => void closeFollowUp()}>Clôturer</Button>}
        </div>
      )}
    </>
  )
}

function OptimizationPlans({ run, whyOpen, onToggleWhy }: { run: OptimizationRun; whyOpen: boolean; onToggleWhy: () => void }) {
  const top = (run.candidates ?? []).slice(0, 3)
  return (
    <div className="mt-2 space-y-2">
      <p className="text-[11px] text-muted">{run.explanation?.why ?? (run.outcome === "NOT_APPLICABLE" ? "Optimisation de dispatch non applicable." : `Résultat : ${run.outcome}`)}</p>
      {run.weatherStatus && <p className="text-[10px] text-muted-2">Météo : {run.weatherStatus} (affichage uniquement, non notée)</p>}
      {top.map((plan: OptimizationCandidate) => (
        <article key={plan.candidateId} className={cn("rounded-md border px-3 py-2", plan.candidateId === run.recommendedCandidateId ? "border-accent/40 bg-accent-soft/30" : "border-border")}>
          <div className="flex flex-wrap items-center gap-1.5 text-[10px]">
            <Badge variant="outline">{plan.isCurrent ? "Plan actuel" : "Candidat"}</Badge>
            {plan.score == null && <Badge variant="outline">non évalué</Badge>}
            <span className="ml-auto tabular-nums text-muted-2">{plan.score != null ? `score ${plan.score}` : "score —"}</span>
          </div>
          <p className="mt-1 text-[12px] font-medium text-foreground">{plan.loaderCode ?? "Chargeuse"} → {plan.destZoneCode ?? "destination actuelle"}</p>
          <p className="text-[11px] text-muted">
            Travel {plan.travelMinutes != null ? `${plan.travelMinutes} min` : "inconnu"} · Attente {plan.waitMinutes != null ? `${plan.waitMinutes} min` : "inconnue"}
            {plan.distanceKm != null ? ` · ${plan.distanceKm} km` : ""}
            {plan.roadIds.length ? ` · ${plan.roadIds.join(" → ")}` : ""}
          </p>
          {plan.constraintNotes.length > 0 && <p className="text-[10px] text-muted-2">{plan.constraintNotes.join(" · ")}</p>}
        </article>
      ))}
      <AiWhyButton expanded={whyOpen} onClick={onToggleWhy} />
      <AiExplanationPanel open={whyOpen}>
        <AiExplanationBlock label="Moteur">Optimiseur déterministe {run.optimizerVersion}. Pas de LLM.</AiExplanationBlock>
        <AiExplanationBlock label="Score">{`score = w_travel × travel + w_wait × attente si les deux sont connus. Poids : ${JSON.stringify(run.explanation?.weights ?? run.weights)}`}</AiExplanationBlock>
        <AiExplanationBlock label="Contraintes">CLOSED/UNKNOWN non routables. Destination actuelle conservée. Météo non notée.</AiExplanationBlock>
      </AiExplanationPanel>
    </div>
  )
}
