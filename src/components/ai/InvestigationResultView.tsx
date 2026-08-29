import {
  Activity,
  AlertTriangle,
  ArrowDown,
  ArrowRight,
  ArrowUp,
  Check,
  CheckCircle2,
  CircleHelp,
  Database,
  GitBranch,
  Minus,
  RefreshCw,
  Search,
  ShieldCheck,
  UserCheck,
  XCircle,
} from "lucide-react"
import type { ReactNode } from "react"

import type { EvidenceItem, InvestigationResult } from "@/lib/api/types/ai"
import {
  formatInvestigationTime,
  hypothesisRank,
  keyEvidence,
  metricLabel,
  operatorText,
} from "@/lib/ai/investigationReport"
import {
  CONFIDENCE_LABEL,
  DIAGNOSIS_STATUS_LABEL,
  investigationFailure,
} from "@/lib/ai/investigationPresentation"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

const DIAGNOSIS_VISUAL = {
  CONFIRMED: { badge: "success" as const, border: "border-success/35", surface: "bg-success/5", icon: CheckCircle2 },
  PROBABLE: { badge: "warning" as const, border: "border-warning/35", surface: "bg-warning/5", icon: AlertTriangle },
  INCONCLUSIVE: { badge: "outline" as const, border: "border-border-strong", surface: "bg-surface", icon: CircleHelp },
}

const HYPOTHESIS_LABEL = {
  BEST_SUPPORTED: "Mieux étayée",
  ALTERNATIVE: "Alternative",
  WEAK: "Support faible",
  CONTRADICTED: "Contredite",
}

function ReportHeading({ children }: { children: ReactNode }) {
  return <h3 className="mb-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-2">{children}</h3>
}

function DirectionIcon({ direction }: { direction: "up" | "down" | "stable" | "none" }) {
  if (direction === "up") return <ArrowUp aria-label="Hausse" className="size-4 text-warning" />
  if (direction === "down") return <ArrowDown aria-label="Baisse" className="size-4 text-accent" />
  if (direction === "stable") return <Minus aria-label="Stable" className="size-4 text-muted" />
  return <Activity aria-hidden="true" className="size-4 text-muted-2" />
}

export function EvidenceValue({ evidence }: { evidence: EvidenceItem }) {
  if (!evidence.available || evidence.value == null) return <span>Indisponible ({evidence.status ?? "UNAVAILABLE"})</span>
  return <span className="break-words whitespace-pre-wrap">{typeof evidence.value === "object" ? JSON.stringify(evidence.value, null, 2) : String(evidence.value)}{evidence.unit ? ` ${evidence.unit}` : ""}</span>
}

function FailedInvestigation({ result, onRetry }: { result: InvestigationResult; onRetry?: () => void }) {
  return <section className="rounded-lg border border-danger/30 bg-danger/5 p-4" role="alert">
    <div className="flex items-start gap-3"><XCircle className="mt-0.5 size-5 shrink-0 text-danger" /><div className="min-w-0 flex-1">
      <p className="text-[10px] font-semibold uppercase tracking-wide text-danger">Analyse IA indisponible</p>
      <h3 className="mt-1 text-sm font-semibold">MinePulse n’a pas pu terminer l’investigation.</h3>
      <p className="mt-1 text-[12px] text-muted">{investigationFailure(result.error) ?? "Investigation interrompue avant la construction d’une conclusion."}</p>
      {result.evidence.length > 0 && <p className="mt-2 text-[11px] text-muted">{result.evidence.length} élément{result.evidence.length === 1 ? "" : "s"} de preuve déjà collecté{result.evidence.length === 1 ? "" : "s"}.</p>}
      {onRetry && <Button size="sm" variant="outline" className="mt-3" onClick={onRetry}><RefreshCw />Actualiser l’investigation</Button>}
    </div></div>
  </section>
}

function DiagnosisSummary({ result }: { result: InvestigationResult }) {
  const conclusion = result.conclusion
  if (!conclusion) return null
  const visual = DIAGNOSIS_VISUAL[conclusion.diagnosis_status]
  const Icon = visual.icon
  const cause = conclusion.root_cause ? operatorText(conclusion.root_cause) : "Les preuves disponibles ne permettent pas d’identifier une cause racine fiable."
  const uncertainty = conclusion.unresolved_uncertainties[0]
  const normalizedCause = conclusion.root_cause?.toLocaleLowerCase().replace(/[^\p{L}\p{N}]+/gu, " ").trim()
  const normalizedSummary = conclusion.summary.toLocaleLowerCase().replace(/[^\p{L}\p{N}]+/gu, " ").trim()
  const summaryAddsInformation = !normalizedCause || !normalizedSummary.includes(normalizedCause)
  return <section className={cn("rounded-lg border p-4", visual.border, visual.surface)}>
    <div className="flex items-start gap-3"><Icon className="mt-0.5 size-5 shrink-0" /><div className="min-w-0 flex-1">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant={visual.badge}>{DIAGNOSIS_STATUS_LABEL[conclusion.diagnosis_status]}</Badge>
        <span className="text-[11px] text-muted">Confiance causale : <strong className="font-semibold text-foreground">{CONFIDENCE_LABEL[conclusion.confidence]}</strong></span>
        {conclusion.diagnosis_status === "PROBABLE" && <span className="text-[10px] text-muted-2">Confirmation incomplète</span>}
      </div>
      <h2 className="mt-2 text-[15px] font-semibold leading-snug text-foreground">{cause}</h2>
      {conclusion.diagnosis_status !== "INCONCLUSIVE" && summaryAddsInformation && <p className="mt-1 text-[12px] leading-relaxed text-muted">{operatorText(conclusion.summary)}</p>}
      {uncertainty && <div className="mt-3 flex gap-2 border-t border-border/70 pt-2 text-[11px] text-muted"><CircleHelp className="mt-0.5 size-3.5 shrink-0" /><p><span className="font-medium text-foreground">Incertitude :</span> {operatorText(uncertainty)}</p></div>}
    </div></div>
  </section>
}

function KeyEvidence({ result }: { result: InvestigationResult }) {
  const evidence = keyEvidence(result)
  return <section data-testid="key-evidence"><ReportHeading>Pourquoi MinePulse pense cela</ReportHeading>
    {evidence.length === 0 ? <div className="rounded-md border border-border bg-surface px-3 py-3 text-[11px] text-muted">Aucune preuve déterminante disponible.</div> : <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
      {evidence.map((item) => <article key={item.key} data-evidence-summary="true" className="rounded-md border border-border bg-surface px-3 py-2.5"><div className="flex items-start gap-2"><DirectionIcon direction={item.direction} /><div className="min-w-0">
        <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-2">{item.label}</p>
        <p className={cn("mt-0.5 text-[13px] font-semibold tabular-nums", !item.available && "text-muted")}>{item.value}</p>
        {item.meaning && <p className="mt-0.5 text-[10px] text-muted">{item.meaning}</p>}
        {item.timestamp && <time className="mt-1 block text-[10px] tabular-nums text-muted-2" dateTime={item.timestamp}>{formatInvestigationTime(item.timestamp)}</time>}
      </div></div></article>)}
    </div>}
  </section>
}

function CausalStory({ result }: { result: InvestigationResult }) {
  const conclusion = result.conclusion
  if (!conclusion) return null
  const observed = conclusion.observed_condition ? operatorText(conclusion.observed_condition) : "Condition opérationnelle signalée"
  const hasCausalMechanism = conclusion.causal_depth > 0 && conclusion.root_cause
  const steps = hasCausalMechanism ? [operatorText(conclusion.root_cause!), observed] : [observed, "Mécanisme causal non établi", "Vérification complémentaire requise"]
  return <section><ReportHeading>Ce qui semble s’être passé</ReportHeading><div className="rounded-md border border-border bg-surface px-3 py-3">
    <div className="flex flex-col gap-1.5 sm:flex-row sm:items-center">{steps.map((step, index) => <div key={`${step}-${index}`} className="contents">
      <div className={cn("min-w-0 flex-1 rounded-md px-2.5 py-2 text-[11px] font-medium", index === 0 && hasCausalMechanism ? "bg-accent-soft text-accent-strong" : "bg-surface-2 text-foreground")}>{step}</div>
      {index < steps.length - 1 && <ArrowRight aria-hidden="true" className="mx-auto size-3.5 shrink-0 rotate-90 text-muted-2 sm:rotate-0" />}
    </div>)}</div>
    {conclusion.contributing_factors.length > 0 && <div className="mt-2 border-t border-border pt-2"><p className="text-[10px] font-medium text-muted">Facteurs contributifs</p><ul className="mt-1 space-y-1 text-[10px] text-muted">{conclusion.contributing_factors.map((factor, index) => <li key={index} className="flex min-w-0 gap-1.5"><span aria-hidden="true">•</span><span className="min-w-0 break-words">{operatorText(factor.statement)}</span></li>)}</ul></div>}
  </div></section>
}

function Recommendation({ result }: { result: InvestigationResult }) {
  const recommendation = result.recommendation
  return <section><ReportHeading>Action recommandée</ReportHeading><div className="rounded-md border border-accent/25 bg-accent-soft/35 px-3.5 py-3">
    {recommendation ? <><p className="text-[13px] font-semibold leading-relaxed text-foreground">{operatorText(recommendation.description)}</p><p className="mt-1 text-[11px] leading-relaxed text-muted">{operatorText(recommendation.rationale)}</p>
      {recommendation.operational_constraints.length > 0 && <ul className="mt-2 list-inside list-disc text-[10px] text-muted">{recommendation.operational_constraints.map((constraint) => <li key={constraint}>{operatorText(constraint)}</li>)}</ul>}
    </> : <p className="text-[12px] text-muted">Aucune action recommandée disponible.</p>}
    <div className="mt-2 flex items-center gap-1.5 border-t border-accent/15 pt-2 text-[10px] font-medium text-foreground"><UserCheck className="size-3.5 text-accent" />Validation humaine requise · aucune action automatique</div>
  </div></section>
}

function InvestigationProcess({ result }: { result: InvestigationResult }) {
  const sourceCount = new Set(result.evidence.map((item) => item.source_tool)).size
  const extraRequests = result.evidence_request_history.filter((item) => item.outcome !== "DUPLICATE_SKIPPED").length
  const stages = [
    result.operational_context ? "Contexte opérationnel récupéré" : "Contexte opérationnel indisponible",
    `${sourceCount} source${sourceCount === 1 ? "" : "s"} de preuve analysée${sourceCount === 1 ? "" : "s"}`,
    `${result.hypotheses.length} hypothèse${result.hypotheses.length === 1 ? "" : "s"} évaluée${result.hypotheses.length === 1 ? "" : "s"}`,
    `${result.contradictions.length} contradiction${result.contradictions.length === 1 ? "" : "s"} identifiée${result.contradictions.length === 1 ? "" : "s"}`,
    ...(extraRequests ? [`${extraRequests} demande${extraRequests === 1 ? "" : "s"} de preuve complémentaire vérifiée${extraRequests === 1 ? "" : "s"}`] : []),
    ...(result.conclusion ? ["Conclusion construite"] : []),
    ...(result.recommendation ? ["Recommandation générée"] : []),
  ]
  return <details className="rounded-md border border-border bg-surface"><summary className="cursor-pointer select-none px-3 py-2.5 text-[11px] font-semibold">Processus d’investigation</summary><ol className="space-y-1 border-t border-border px-3 py-2.5 text-[11px] text-muted">
    {stages.map((stage, index) => <li key={stage} className="flex items-center gap-2"><Check className="size-3.5 text-success" /><span>{stage}</span>{index === 1 && <span className="ml-auto text-[10px] text-muted-2">{result.evidence.length} élément{result.evidence.length === 1 ? "" : "s"}</span>}</li>)}
  </ol></details>
}

function Hypotheses({ result }: { result: InvestigationResult }) {
  return <details data-testid="hypotheses-detail" className="rounded-md border border-border bg-surface"><summary className="cursor-pointer select-none px-3 py-2.5 text-[11px] font-semibold">Hypothèses examinées ({result.hypotheses.length})</summary><div className="space-y-2 border-t border-border p-3">
    {result.hypotheses.length === 0 && <p className="text-[11px] text-muted">Aucune hypothèse exploitable.</p>}
    {result.hypotheses.map((hypothesis, index) => {
      const rank = hypothesisRank(hypothesis, result, index)
      return <article key={hypothesis.hypothesis_id} className="rounded-md border border-border bg-background px-3 py-2.5"><div className="flex flex-wrap items-center gap-2">
        <span className="text-[11px] font-semibold">{index + 1}. {operatorText(hypothesis.statement)}</span>
        <Badge variant={rank === "BEST_SUPPORTED" ? "accent" : rank === "CONTRADICTED" ? "danger" : "outline"}>{HYPOTHESIS_LABEL[rank]}</Badge>
        <span className="ml-auto text-[10px] text-muted">Support : {CONFIDENCE_LABEL[hypothesis.confidence]}</span>
      </div><p className="mt-1 text-[11px] leading-relaxed text-muted">{operatorText(hypothesis.rationale)}</p>
      {hypothesis.contradictory_evidence_ids.length > 0 && <p className="mt-1 text-[10px] text-danger">{hypothesis.contradictory_evidence_ids.length} preuve{hypothesis.contradictory_evidence_ids.length === 1 ? "" : "s"} contradictoire{hypothesis.contradictory_evidence_ids.length === 1 ? "" : "s"}</p>}
      </article>
    })}
  </div></details>
}

export function InvestigationUncertainty({ result }: { result: InvestigationResult }) {
  const uncertainties = result.conclusion?.unresolved_uncertainties ?? []
  const total = uncertainties.length + result.requested_information.length + result.contradictions.length
  if (!total) return null
  return <details data-testid="uncertainty-detail" className="rounded-md border border-border bg-surface"><summary className="cursor-pointer select-none px-3 py-2.5 text-[11px] font-semibold">Incertitudes et contradictions ({total})</summary><div className="space-y-3 border-t border-border px-3 py-2.5 text-[11px]">
    {uncertainties.length > 0 && <section><p className="font-medium">Ce qui empêche une confirmation complète</p><ul className="mt-1 list-inside list-disc space-y-1 text-muted">{uncertainties.map((item, index) => <li key={index}>{operatorText(item)}</li>)}</ul></section>}
    {result.contradictions.length > 0 && <section><p className="font-medium">Signaux contradictoires</p><ul className="mt-1 list-inside list-disc space-y-1 text-muted">{result.contradictions.map((item, index) => <li key={index}>{operatorText(item.description)}</li>)}</ul></section>}
    {result.requested_information.length > 0 && <section><p className="font-medium">Informations encore recherchées</p><ul className="mt-1 list-inside list-disc space-y-1 text-muted">{result.requested_information.map((item) => <li key={item.request_id}>{operatorText(item.reason)}</li>)}</ul></section>}
  </div></details>
}

export function InvestigationEvidence({ result }: { result: InvestigationResult }) {
  return <details data-testid="technical-evidence" className="rounded-md border border-border bg-surface"><summary className="cursor-pointer select-none px-3 py-2.5 text-[11px] font-semibold">Voir toutes les preuves ({result.evidence.length})</summary><div className="border-t border-border p-3 text-[11px]">
    {result.evidence.length === 0 && <p className="text-muted">Éléments opérationnels indisponibles.</p>}
    {result.evidence.map((evidence) => <details key={evidence.evidence_id} className="mb-2 rounded-md border border-border bg-background p-2 last:mb-0"><summary className="cursor-pointer"><span className="font-medium">{metricLabel(evidence.metric)}</span><span className="ml-2 text-[10px] text-muted">{evidence.kind} · {evidence.available ? "Disponible" : "Indisponible"}</span></summary>
      <dl className="mt-2 grid gap-1 text-[10px] text-muted sm:grid-cols-2"><div><dt className="text-muted-2">Source</dt><dd>{evidence.source_tool}</dd></div><div><dt className="text-muted-2">Horodatage</dt><dd>{formatInvestigationTime(evidence.observed_at)}</dd></div><div className="sm:col-span-2"><dt className="text-muted-2">Provenance</dt><dd className="break-all">{evidence.source_service}</dd></div></dl>
      {evidence.notes && <p className="mt-2 text-muted">{evidence.notes}</p>}
      <details className="mt-2 rounded border border-dashed border-border px-2 py-1.5 font-mono text-[10px]"><summary className="cursor-pointer text-muted-2">Données structurées et identifiants</summary><div className="mt-2 max-h-60 overflow-auto"><EvidenceValue evidence={evidence} /></div><p className="mt-2 break-all text-muted-2">{evidence.evidence_id}</p></details>
    </details>)}
  </div></details>
}

export function InvestigationResultView({ result, onRetry }: { result: InvestigationResult; onRetry?: () => void }) {
  if (result.status === "FAILED") return <div className="space-y-3"><FailedInvestigation result={result} onRetry={onRetry} /><InvestigationEvidence result={result} /></div>
  return <div className="space-y-4 text-[12px]">
    <DiagnosisSummary result={result} />
    <KeyEvidence result={result} />
    <CausalStory result={result} />
    <Recommendation result={result} />
    <section><ReportHeading>Impact</ReportHeading><div className="rounded-md border border-border bg-surface px-3 py-2.5 text-[11px] text-muted">Impact non quantifié</div></section>
    <div className="space-y-2"><Hypotheses result={result} /><InvestigationUncertainty result={result} /><InvestigationProcess result={result} /><InvestigationEvidence result={result} /></div>
    <footer className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-border pt-2 text-[10px] text-muted-2">
      <span className="inline-flex items-center gap-1"><Database className="size-3" />{result.operational_context?.site_name ?? `Site ${result.trigger.site_id}`}</span>
      <span className="inline-flex items-center gap-1"><Search className="size-3" />{result.iteration_count} cycle{result.iteration_count === 1 ? "" : "s"} d’analyse</span>
      <span className="inline-flex items-center gap-1"><GitBranch className="size-3" />{result.graph_version}</span>
      <span className="inline-flex items-center gap-1"><ShieldCheck className="size-3" />Décision assistée</span>
    </footer>
  </div>
}
