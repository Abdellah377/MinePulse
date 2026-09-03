import { useEffect, useMemo, useRef, useState } from "react"
import { MessageSquare } from "lucide-react"
import { investigationKey, useInvestigationStore } from "@/lib/store/useInvestigationStore"
import { useWorkspaceStore } from "@/lib/store/useWorkspaceStore"
import { useOpsStore } from "@/lib/store/useOpsStore"
import { useAlertFeedStore } from "@/lib/store/useAlertFeedStore"
import type { WorkspacePanelProps } from "@/components/workspace/WorkspaceHost"
import { CONFIDENCE_LABEL, DIAGNOSIS_STATUS_LABEL, investigationFailure } from "@/lib/ai/investigationPresentation"
import { compactOperatorText, operatorText } from "@/lib/ai/investigationReport"
import { mergeInboxItems, nextInboxSelection, removeInboxItem } from "@/lib/ai/actionsInbox"
import { buildUserInvestigateTrigger } from "@/lib/ai/investigationTrigger"
import {
  FMS_DECISION_NOTE,
  INVESTIGATION_REQUIRED_COPY,
  actionsIaVisibility,
  resolveActionsIaView,
  shouldStartOptimizationWorkflow,
} from "@/lib/ai/actionsIaView"
import {
  classifyOptimizationImpact,
  composeOperatorRecommendedAction,
  isScoreEquationText,
  optimizationWorkflowBanner,
  optimizerOperatorStatus,
  planCandidateLabel,
  technicalOptimizationDetails,
  visibleOptimizationPlans,
  weatherOperatorLabel,
} from "@/lib/ai/optimizationDisplay"
import { CompactPlanImpact, OptimizationImpactCard } from "@/components/ai/OptimizationImpact"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Textarea } from "@/components/ui/textarea"
import { cn } from "@/lib/utils"
import { aiApi } from "@/lib/api/ai"
import type { InvestigationResult, JsonValue } from "@/lib/api/types/ai"
import type {
  DiscussionThread,
  FollowUpStatus,
  RecommendationDecisionType,
  RecommendationDecisionView,
  RejectionReasonCategory,
} from "@/lib/api/types/actionsIa"
import { DECISION_STATUS_LABEL, FOLLOW_UP_STATUS_LABEL, REJECTION_REASON_LABEL } from "@/lib/api/types/actionsIa"
import type { ActionsInboxItem, OptimizationCandidate, OptimizationRun } from "@/lib/api/types/optimization"
import { SEVERITY_CONFIG } from "@/lib/status"
import { operationalAlertTime } from "@/lib/alerts/order"
import { formatOperationalDateTime, operationalTimeAgo } from "@/lib/format"
import { ALERT_STATUS_LABEL } from "@/lib/mock/types"

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
  const entries = useInvestigationStore((s) => s.entries)
  const retrieve = useInvestigationStore((s) => s.retrieve)
  const lookup = useInvestigationStore((s) => s.lookup)
  const start = useInvestigationStore((s) => s.start)
  const openWorkspace = useWorkspaceStore((s) => s.openWorkspace)
  const activateTab = useWorkspaceStore((s) => s.activateTab)
  const updateAlertStatus = useOpsStore((s) => s.updateAlertStatus)
  const selectedSiteId = useOpsStore((s) => s.selectedSiteId)
  const selectedShiftId = useOpsStore((s) => s.selectedShiftId)
  const sites = useOpsStore((s) => s.sites)
  const shifts = useOpsStore((s) => s.shifts)
  const equipmentList = useOpsStore((s) => s.equipment)
  const zones = useOpsStore((s) => s.zones)
  const simNowIso = useOpsStore((s) => s.simNowIso)
  const activeCount = useAlertFeedStore((s) => s.activeCount)
  const [inbox, setInbox] = useState<ActionsInboxItem[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(contextAlertId ?? null)
  const [resolvedOverlay, setResolvedOverlay] = useState<ActionsInboxItem | null>(null)
  const [hasMore, setHasMore] = useState(false)
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [loadingMore, setLoadingMore] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [run, setRun] = useState<OptimizationRun | null>(null)
  const [detailReady, setDetailReady] = useState(false)
  const [optimizingWorkflow, setOptimizingWorkflow] = useState(false)
  const [decisionView, setDecisionView] = useState<RecommendationDecisionView | null>(null)
  const [thread, setThread] = useState<DiscussionThread | null>(null)
  const [discussOpen, setDiscussOpen] = useState(false)
  const [formMode, setFormMode] = useState<"REJECTED" | "MODIFIED" | null>(null)
  const [reasonCategory, setReasonCategory] = useState<RejectionReasonCategory>("CONTRAINTE_NON_CONNUE_PAR_IA")
  const [reasonText, setReasonText] = useState("")
  const [alternative, setAlternative] = useState("")
  const [actorLabel, setActorLabel] = useState("")
  const [draft, setDraft] = useState("")
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const [selectedPlanId, setSelectedPlanId] = useState<string | null>(null)
  const workflowFor = useRef<string | null>(null)
  const selectedIdRef = useRef<string | null>(selectedId)
  selectedIdRef.current = selectedId
  const overlayRef = useRef<ActionsInboxItem | null>(resolvedOverlay)
  overlayRef.current = resolvedOverlay
  const navKeyRef = useRef(`${contextAlertId ?? ""}|${selectedSiteId}|${selectedShiftId}`)

  const selected = inbox.find((row) => row.id === selectedId)
    ?? (resolvedOverlay?.id === selectedId ? resolvedOverlay : null)
    ?? (selectedId ? null : inbox[0])
  const alertId = selected?.id ?? contextAlertId ?? null
  const id = selected?.investigationId ?? investigationId
  const siteId = sites.find((row) => row.id === selectedSiteId)?.databaseId
  const shiftId = shifts.find((row) => row.id === selectedShiftId)?.databaseId
  const scope = siteId && alertId ? { site_id: siteId, shift_id: shiftId, source_record_id: alertId } : null
  const scopeKey = scope ? investigationKey(scope) : ""
  const entry = (scopeKey ? entries[scopeKey] : undefined)
    ?? (id ? entries[id] : undefined)
    ?? (investigationId ? entries[investigationId] : undefined)
  const equipment = equipmentList.find((row) => row.id === selected?.equipmentId)
  const selectedZone = zones.find((row) => row.id === selected?.zoneId)

  useEffect(() => {
    let cancelled = false
    setLoadError(null)
    const navKey = `${contextAlertId ?? ""}|${selectedSiteId}|${selectedShiftId}`
    const explicitContext = navKeyRef.current !== navKey
    navKeyRef.current = navKey
    if (explicitContext) setResolvedOverlay(null)
    void aiApi.listInbox({ limit: 20 }, opsCtx()).then(async (page) => {
      if (cancelled) return
      let items = page.items
      let overlay: ActionsInboxItem | null = explicitContext ? null : overlayRef.current
      setHasMore(page.hasMore)
      setNextCursor(page.nextCursor)
      const missingIds = new Set<string>()
      if (contextAlertId && !items.some((row) => row.id === contextAlertId)) missingIds.add(contextAlertId)
      const currentId = selectedIdRef.current
      if (currentId && !items.some((row) => row.id === currentId) && overlay?.id !== currentId) {
        missingIds.add(currentId)
      }
      for (const missingId of missingIds) {
        try {
          const detail = await aiApi.getInboxDetail(missingId, opsCtx())
          if (cancelled) return
          if (detail.alert.status === "resolved") overlay = detail.alert
          else items = mergeInboxItems(items, [detail.alert], { prepend: true })
        } catch {
          if (!cancelled && missingId === contextAlertId) setLoadError("Dossier introuvable.")
        }
      }
      if (cancelled) return
      if (overlay) setResolvedOverlay(overlay)
      setInbox(items)
      const selectable = overlay ? [...items, overlay] : items
      setSelectedId((current) => nextInboxSelection(selectable, current, contextAlertId, { explicitContext }))
    }).catch(() => {
      if (!cancelled) {
        setInbox([])
        setLoadError("File Actions IA indisponible.")
      }
    })
    return () => { cancelled = true }
  }, [contextAlertId, selectedSiteId, selectedShiftId, activeCount])

  useEffect(() => {
    if (contextAlertId) setSelectedId(contextAlertId)
  }, [contextAlertId])

  useEffect(() => {
    if (siteId && alertId) void lookup({ site_id: siteId, shift_id: shiftId, source_record_id: alertId })
  }, [siteId, shiftId, alertId, lookup])
  useEffect(() => { if (id) void retrieve(id) }, [id, retrieve])
  useEffect(() => {
    if (!alertId) {
      setDetailReady(false)
      setRun(null)
      return
    }
    let cancelled = false
    setDetailReady(false)
    setRun(null)
    workflowFor.current = null
    void aiApi.getInboxDetail(alertId, opsCtx()).then((detail) => {
      if (cancelled) return
      setActionError(null)
      const latest = detail.latestRun
      const nextRun = latest ? { ...latest, alertId, snapshotDigest: latest.snapshotDigest ?? null } : null
      setRun(nextRun)
      setDetailReady(true)
      if (nextRun) {
        setInbox((rows) => rows.map((row) => row.id === alertId ? { ...row, latestRunOutcome: nextRun.outcome, optimizationEligible: nextRun.eligibility === "OPTIMIZABLE" || detail.alert.optimizationEligible } : row))
        const displayedId = nextRun.displayedCandidateIds?.[0]
        const fallbackRec = nextRun.candidates.find((plan) => !plan.isCurrent)?.candidateId
        const baselineId = nextRun.baselineCandidateId ?? nextRun.candidates.find((plan) => plan.isCurrent)?.candidateId
        setSelectedPlanId(displayedId ?? fallbackRec ?? baselineId ?? nextRun.recommendedCandidateId ?? null)
      } else {
        setSelectedPlanId(null)
      }
      if (detail.decision) {
        setDecisionView({
          investigation_id: detail.decision.investigation_id,
          decision_type: detail.decision.decision_type,
          follow_up_status: detail.decision.follow_up_status,
          decision: detail.decision,
        })
      }
    }).catch(() => {
      if (!cancelled) {
        setRun(null)
        setDetailReady(true)
        setActionError("Dossier alerte indisponible.")
      }
    })
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
  const confidence = result?.conclusion ? CONFIDENCE_LABEL[result.conclusion.confidence] : null
  const failure = entry?.error ?? investigationFailure(result?.error)
  const roads = useMemo(() => roadImpact(result), [result])
  const status = decisionView?.decision_type ?? "PENDING"
  const record = decisionView?.decision ?? null
  const followUp = record?.follow_up_status ?? decisionView?.follow_up_status ?? null
  const eligible = selected?.optimizationEligible ?? false
  const handled = selected?.status === "resolved"
  const viewInput = useMemo(() => ({
    hasInvestigation: Boolean(selected?.hasInvestigation || result),
    entryPhase: entry?.phase,
    resultStatus: result?.status ?? null,
    optimizationEligible: eligible,
    runOutcome: run?.outcome ?? null,
    workflowStatus: run?.workflowStatus ?? null,
    optimizing: optimizingWorkflow,
  }), [selected?.hasInvestigation, result, entry?.phase, eligible, run?.outcome, run?.workflowStatus, optimizingWorkflow])
  const viewState = resolveActionsIaView(viewInput)
  const vis = actionsIaVisibility(viewState)
  const impact = useMemo(
    () => classifyOptimizationImpact(run?.candidates, selectedPlanId),
    [run?.candidates, selectedPlanId],
  )
  const action = useMemo(
    () => composeOperatorRecommendedAction({
      run,
      investigationDescription: rec?.description,
    }),
    [run, rec],
  )
  const technical = useMemo(() => (run ? technicalOptimizationDetails(run) : null), [run])
  const whyPoints = useMemo(() => {
    const points: string[] = []
    if (result?.conclusion?.root_cause) points.push(operatorText(result.conclusion.root_cause))
    else if (result?.conclusion?.summary) points.push(operatorText(result.conclusion.summary))
    for (const constraint of rec?.operational_constraints ?? []) {
      const text = operatorText(constraint)
      if (text && !points.includes(text) && !isScoreEquationText(text)) points.push(text)
    }
    const why = run?.explanation?.why
    if (why && !isScoreEquationText(why) && !why.includes("Acceptation ≠ application FMS") && !why.includes("Météo affichée")) {
      points.push(why)
    }
    const others = (run?.candidates ?? []).filter((plan) => plan.candidateId !== run?.recommendedCandidateId && plan.rankReason)
    for (const plan of others.slice(0, 2)) {
      if (plan.rankReason && !isScoreEquationText(plan.rankReason)) {
        points.push(`${plan.loaderCode ?? "Plan"} : ${plan.rankReason}`)
      }
    }
    if (roads) {
      points.push(`Preuve routière : ${roads.distance != null ? `${roads.distance} km` : "distance inconnue"}${roads.minutes != null ? ` · ${roads.minutes} min` : ""}`)
    }
    return points.slice(0, 4)
  }, [result, rec, run, roads])

  useEffect(() => {
    if (!alertId || !detailReady) return
    if (!shouldStartOptimizationWorkflow(viewInput)) return
    const key = `${alertId}:${result?.investigation_id ?? "inv"}`
    if (workflowFor.current === key) return
    workflowFor.current = key
    let cancelled = false
    setOptimizingWorkflow(true)
    void aiApi.createOptimizationWorkflow(alertId, opsCtx()).then((next) => {
      if (cancelled) return
      setRun(next)
      const displayedId = next.displayedCandidateIds?.[0]
      const fallbackRec = next.candidates.find((plan) => !plan.isCurrent)?.candidateId
      const baselineId = next.baselineCandidateId ?? next.candidates.find((plan) => plan.isCurrent)?.candidateId
      setSelectedPlanId(displayedId ?? fallbackRec ?? baselineId ?? next.recommendedCandidateId ?? null)
      setInbox((rows) => rows.map((row) => row.id === alertId ? { ...row, latestRunOutcome: next.outcome, optimizationEligible: next.eligibility === "OPTIMIZABLE" } : row))
    }).catch(() => {
      if (!cancelled) setActionError("Optimisation de dispatch indisponible.")
    }).finally(() => {
      if (!cancelled) setOptimizingWorkflow(false)
    })
    return () => { cancelled = true }
  }, [alertId, detailReady, viewInput, result?.investigation_id])

  function investigate() {
    if (!siteId || !alertId) return
    const row = selected ?? {
      id: alertId,
      category: "OPERATIONAL",
      title: "",
      description: "",
      severity: "warning" as const,
    }
    void start(buildUserInvestigateTrigger({
      siteId,
      shiftId,
      alert: row,
      equipmentDatabaseId: equipment?.databaseId,
      zoneDatabaseId: selectedZone?.databaseId,
      source: "actions-ui",
    }), { retryFailed: viewState === "investigation_failed" })
  }

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
      await updateAlertStatus(alertId, "resolved", actorLabel || "Chef de poste")
      const { remaining, nextSelectedId } = removeInboxItem(inbox, alertId)
      setInbox(remaining)
      setSelectedId(nextSelectedId)
      setResolvedOverlay(null)
    } catch {
      setActionError("Impossible de marquer le dossier comme traité.")
    } finally {
      setBusy(false)
    }
  }

  async function loadMoreInbox() {
    if (!hasMore || !nextCursor || loadingMore) return
    setLoadingMore(true)
    try {
      const page = await aiApi.listInbox({ limit: 20, cursor: nextCursor }, opsCtx())
      setInbox((rows) => mergeInboxItems(rows, page.items))
      setHasMore(page.hasMore)
      setNextCursor(page.nextCursor)
    } catch {
      setActionError("Chargement de la file impossible.")
    } finally {
      setLoadingMore(false)
    }
  }

  async function runOptimize() {
    if (!alertId) return
    setBusy(true)
    setActionError(null)
    try {
      const next = await aiApi.createOptimizationWorkflow(alertId, opsCtx())
      setRun(next)
      const displayedId = next.displayedCandidateIds?.[0]
      const fallbackRec = next.candidates.find((plan) => !plan.isCurrent)?.candidateId
      const baselineId = next.baselineCandidateId ?? next.candidates.find((plan) => plan.isCurrent)?.candidateId
      setSelectedPlanId(displayedId ?? fallbackRec ?? baselineId ?? next.recommendedCandidateId ?? null)
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

  const decisionControls = (
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
  )

  return (
    <div className="flex h-full overflow-hidden">
      <aside aria-label="File Actions IA" className="flex w-[32%] min-w-[240px] max-w-[340px] flex-col border-r border-border bg-surface">
        <div className="shrink-0 border-b border-border px-3 py-2.5">
          <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-2">Dossiers à traiter</p>
          <p className="text-[12px] text-muted">{inbox.length} dossier{inbox.length > 1 ? "s" : ""} ouvert{inbox.length > 1 ? "s" : ""}</p>
        </div>
        <div
          className="min-h-0 flex-1 overflow-y-auto"
          onScroll={(event) => {
            const node = event.currentTarget
            if (node.scrollHeight - node.scrollTop - node.clientHeight < 80) void loadMoreInbox()
          }}
        >
          {loadError && !inbox.length && (
            <p role="alert" className="px-3 py-8 text-center text-[12px] text-danger">{loadError}</p>
          )}
          {!loadError && !inbox.length && (
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
                  {row.optimizationEligible && <span className="text-accent">Optimisable</span>}
                  <span className="ml-auto tabular-nums text-muted-2">{operationalTimeAgo(operationalAlertTime(row), simNowIso)}</span>
                </div>
                <p className="text-[12px] font-medium text-foreground">{row.equipmentId ?? row.zoneId ?? row.location ?? row.title}</p>
                <p className="text-[10px] text-muted-2">{row.category}</p>
              </button>
            )
          })}
          {loadingMore && <p className="px-3 py-2 text-center text-[10px] text-muted-2">Chargement…</p>}
        </div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col overflow-hidden bg-background">
        <header className="shrink-0 border-b border-border bg-surface px-4 py-3">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-2">Aide à la décision</p>
              <h1 className="mt-0.5 text-[15px] font-semibold text-foreground">
                {selected ? `${selected.equipmentId ?? selected.zoneId ?? "Dossier"} · ${selected.category}` : (inbox.length || loadError ? "Actions IA" : "Aucun dossier")}
              </h1>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button size="sm" variant="outline" onClick={backToAlert}>Voir l’alerte</Button>
              <Button size="sm" disabled={!alertId || handled || busy} onClick={() => void markHandled()}>Marquer comme traité</Button>
            </div>
          </div>
          {failure && <p role="alert" className="mt-2 text-xs text-danger">{failure}</p>}
          {actionError && <p role="alert" className="mt-2 text-xs text-danger">{actionError}</p>}
        </header>
        <main className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4">
          {selected && (
            <section className="rounded-md border border-border bg-surface px-3.5 py-3">
              <h2 className="text-[11px] font-semibold uppercase tracking-wide text-muted-2">Problème</h2>
              <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[11px]">
                <Badge className={cn(SEVERITY_CONFIG[selected.severity].bg, SEVERITY_CONFIG[selected.severity].color, "border-transparent")}>{SEVERITY_CONFIG[selected.severity].label}</Badge>
                <Badge variant="outline">{ALERT_STATUS_LABEL[selected.status]}</Badge>
                <span className="tabular-nums text-muted-2">{formatOperationalDateTime(operationalAlertTime(selected))}</span>
              </div>
              <p className="mt-2 text-[13px] font-medium text-foreground">{selected.equipmentId ?? selected.location ?? selected.title}</p>
              <p className="mt-1 line-clamp-2 text-[12px] text-muted">{operatorText(selected.description)}</p>
            </section>
          )}

          {vis.showInvestiguer && (selected || contextAlertId) && (
            <section className="rounded-md border border-border bg-surface px-3.5 py-3">
              <h2 className="text-[11px] font-semibold uppercase tracking-wide text-muted-2">Investigation requise</h2>
              <p className="mt-2 text-[12px] text-muted">{INVESTIGATION_REQUIRED_COPY}</p>
              <Button className="mt-3" size="sm" disabled={!alertId || busy} onClick={() => void investigate()}>
                {viewState === "investigation_failed" ? "Relancer l’investigation" : "Investiguer"}
              </Button>
            </section>
          )}

          {vis.showInvestigationProgress && (
            <section className="rounded-md border border-border bg-surface px-3.5 py-3">
              <h2 className="text-[11px] font-semibold uppercase tracking-wide text-muted-2">Investigation</h2>
              <p className="mt-2 text-[12px] text-muted">Analyse IA en cours…</p>
            </section>
          )}

          {vis.showAction && (
            <section className={cn("rounded-md border px-3.5 py-3", status === "ACCEPTED" ? "border-accent/40 bg-accent-soft/40" : "border-border bg-surface")}>
              <h2 className="text-[11px] font-semibold uppercase tracking-wide text-muted-2">Action recommandée</h2>
              {action ? (
                <>
                  <p className="mt-2 text-[15px] font-semibold leading-snug text-foreground">{operatorText(action.text)}</p>
                  {action.source === "investigation" && rec?.rationale && (
                    <p className="mt-1.5 text-[12px] text-muted">{operatorText(rec.rationale)}</p>
                  )}
                  {action.source === "investigation" && confidence && (
                    <p className="mt-2 text-[11px] text-muted-2">Confiance {confidence}</p>
                  )}
                  {vis.showDecisionControls && decisionControls}
                </>
              ) : (
                <p className="mt-2 text-[12px] text-muted">Recommandation non évaluée ou indisponible.</p>
              )}
            </section>
          )}

          {vis.showDispatchOptions && (
            <section className="rounded-md border border-accent/30 bg-surface px-3.5 py-3">
              <div className="flex items-center justify-between gap-2">
                <h2 className="text-[11px] font-semibold uppercase tracking-wide text-muted-2">Options de dispatch</h2>
                {run && (
                  <Button size="sm" variant="outline" disabled={!alertId || busy || optimizingWorkflow} onClick={() => void runOptimize()}>Recalculer</Button>
                )}
              </div>
              {run && viewState !== "optimizing" ? (
                <OptimizationPlans
                  run={run}
                  selectedPlanId={selectedPlanId}
                  onSelectPlan={setSelectedPlanId}
                />
              ) : (
                <p className="mt-2 text-[12px] text-muted">Calcul des options de dispatch…</p>
              )}
            </section>
          )}

          {vis.showImpact && run && <OptimizationImpactCard view={impact} />}

          {vis.showAction && whyPoints.length > 0 && (
            <details className="rounded-md border border-border bg-surface px-3.5 py-3">
              <summary className="cursor-pointer text-[12px] font-semibold text-foreground">Pourquoi cette recommandation ?</summary>
              <ul className="mt-2 list-disc space-y-1 pl-4 text-[12px] text-muted">
                {whyPoints.map((point) => <li key={point}>{point}</li>)}
              </ul>
              {result?.conclusion && (
                <p className="mt-2 text-[11px] text-muted-2">{DIAGNOSIS_STATUS_LABEL[result.conclusion.diagnosis_status]}{result.conclusion.root_cause ? ` — ${compactOperatorText(result.conclusion.root_cause, 80)}` : ""}</p>
              )}
            </details>
          )}

          {vis.showTechnicalDetails && technical && (
            <section className="rounded-md border border-border bg-surface px-3.5 py-3">
              <h2 className="text-[11px] font-semibold uppercase tracking-wide text-muted-2">Détails techniques</h2>
              <p className="mt-2 text-[12px] text-muted">{technical.objectif}</p>
              <p className="mt-1 text-[12px] text-muted">{technical.calcul}</p>
              <p className="mt-1 text-[12px] text-muted">Météo : {weatherOperatorLabel(run?.weatherStatus)}</p>
            </section>
          )}

          {vis.showAction && (
            <section className="rounded-md border border-border bg-surface px-3.5 py-3">
              <h2 className="text-[11px] font-semibold uppercase tracking-wide text-muted-2">Décision et clôture</h2>
              <p className="mt-1 text-[12px] font-medium text-foreground">{DECISION_STATUS_LABEL[status]}{followUp ? ` · ${FOLLOW_UP_STATUS_LABEL[followUp]}` : ""}</p>
              <p className="mt-1 text-[11px] text-muted">« Marquer comme traité » clôt le dossier alerte.</p>
              {record && status !== "PENDING" && (
                <p className="mt-2 text-[12px] text-muted">{formatWhen(record.updated_at)}{record.actor_label ? ` · ${record.actor_label}` : ""}</p>
              )}
            </section>
          )}

          {vis.showAction && (
            <details className="rounded-md border border-border bg-surface px-3.5 py-3" open={discussOpen} onToggle={(event) => setDiscussOpen((event.target as HTMLDetailsElement).open)}>
              <summary className="cursor-pointer text-[12px] font-semibold text-foreground">
                <span className="inline-flex items-center gap-1.5"><MessageSquare className="size-3.5" />Discuter cette recommandation</span>
              </summary>
              <p className="mt-1 text-[11px] text-muted">Hors investigation. Recalculer orchestre le plan ; l’envoi d’un message discute la recommandation. Consulter un dossier n’appelle pas l’IA.</p>
              {id && (
                <div className="mt-3 space-y-2" data-testid="recommendation-discussion">
                  <div className="max-h-48 space-y-2 overflow-y-auto rounded-md border border-border bg-background p-2">
                    {(thread?.messages ?? []).length === 0 && <p className="text-[11px] text-muted">Aucun échange pour l’instant.</p>}
                    {(thread?.messages ?? []).map((message) => (
                      <div key={message.message_id} className="text-[11px]"><p className="font-semibold text-foreground/80">{message.role === "OPERATOR" ? "Opérateur" : "MinePulse"}</p><p className="text-muted">{message.content}</p></div>
                    ))}
                  </div>
                  <Textarea value={draft} onChange={(event) => setDraft(event.target.value)} rows={3} placeholder="Question sur cette recommandation…" />
                  <Button size="sm" disabled={!id || busy || !draft.trim()} onClick={() => void sendDiscussion()}>Envoyer</Button>
                </div>
              )}
            </details>
          )}
        </main>
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
  followUp: FollowUpStatus | null
  closeFollowUp: () => void
}) {
  return (
    <>
      {status === "PENDING" && !formMode && (
        <div className="mt-3 border-t border-border pt-3">
          <p className="text-[11px] font-semibold text-foreground">Votre décision</p>
          <p className="mt-1 text-[11px] text-muted">{FMS_DECISION_NOTE}</p>
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

function OptimizationPlans({
  run,
  selectedPlanId,
  onSelectPlan,
}: {
  run: OptimizationRun
  selectedPlanId: string | null
  onSelectPlan: (id: string) => void
}) {
  const { visible: plans, hiddenCount } = visibleOptimizationPlans(run.candidates, run.displayedCandidateIds)
  const recommendedId = run.displayedCandidateIds?.[0] ?? run.recommendedCandidateId
  const banner = optimizationWorkflowBanner(run)
  let alternativeIndex = 0
  return (
    <div className="mt-2 space-y-2">
      <p className="text-[11px] text-muted">{optimizerOperatorStatus(run)}</p>
      {banner && banner !== optimizerOperatorStatus(run) && (
        <p className={cn("text-[11px]", run.reviewerCaution === banner ? "text-warning" : "text-muted-2")}>{banner}</p>
      )}
      {!plans.length && run.workflowStatus !== "NO_CHANGE_RECOMMENDED" && run.outcome !== "FEASIBLE" && (
        <p className="text-[11px] text-muted">Aucun candidat de dispatch à afficher. Aucun impact n’est inventé.</p>
      )}
      {plans.map((plan) => {
        const named = Boolean(plan.candidateId === recommendedId || plan.candidateRelation === "EQUIVALENT")
        if (!named) alternativeIndex += 1
        return (
          <PlanCandidateButton
            key={plan.candidateId}
            plan={plan}
            rankLabel={planCandidateLabel(plan, recommendedId, alternativeIndex)}
            selected={plan.candidateId === selectedPlanId}
            onSelect={() => onSelectPlan(plan.candidateId)}
            compactImpact={!named}
          />
        )
      })}
      {hiddenCount > 0 && (
        <p className="text-[10px] text-muted-2">+ {hiddenCount} autre{hiddenCount > 1 ? "s" : ""} candidat{hiddenCount > 1 ? "s" : ""} conservé{hiddenCount > 1 ? "s" : ""} dans l’historique</p>
      )}
    </div>
  )
}

function PlanCandidateButton({
  plan,
  rankLabel,
  selected,
  onSelect,
  compactImpact,
}: {
  plan: OptimizationCandidate
  rankLabel: string
  selected: boolean
  onSelect: () => void
  compactImpact: boolean
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={cn(
        "w-full min-w-0 rounded-md border px-3 py-2 text-left",
        selected ? "border-accent/50 bg-accent-soft/40" : "border-border hover:bg-surface-2/70",
      )}
    >
      <div className="flex flex-wrap items-center gap-1.5 text-[10px]">
        <Badge variant="outline">{rankLabel}</Badge>
        {plan.score == null && <Badge variant="outline">non évalué</Badge>}
      </div>
      <p className="mt-1 text-[12px] font-medium text-foreground">{plan.loaderCode ?? "Chargeuse"} → {plan.destZoneCode ?? "destination actuelle"}</p>
      {compactImpact ? (
        <CompactPlanImpact plan={plan} />
      ) : (
        <p className="min-w-0 text-[11px] text-muted">
          {plan.roadIds.length ? plan.roadIds.join(" → ") : "Itinéraire évalué"}
        </p>
      )}
      {plan.constraintNotes.length > 0 && <p className="text-[10px] text-muted-2">{plan.constraintNotes.join(" · ")}</p>}
    </button>
  )
}
