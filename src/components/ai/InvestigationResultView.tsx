import type { InvestigationResult, EvidenceItem } from "@/lib/api/types/ai"
import { CONFIDENCE_LABEL, DIAGNOSIS_STATUS_LABEL, investigationFailure } from "@/lib/ai/investigationPresentation"

export function EvidenceValue({ evidence }: { evidence: EvidenceItem }) {
  if (!evidence.available || evidence.value == null) return <span>Indisponible ({evidence.status ?? "UNAVAILABLE"})</span>
  return <span className="break-words whitespace-pre-wrap">{typeof evidence.value === "object" ? JSON.stringify(evidence.value, null, 2) : String(evidence.value)}{evidence.unit ? ` ${evidence.unit}` : ""}</span>
}

export function InvestigationResultView({ result }: { result: InvestigationResult }) {
  const conclusion = result.conclusion
  const diagnosisLabel = conclusion ? DIAGNOSIS_STATUS_LABEL[conclusion.diagnosis_status] : null
  return <div className="space-y-4 text-[12px]">
    <section><h3 className="mb-1 font-semibold">Conclusion</h3>
      {diagnosisLabel && <p className="font-medium">{diagnosisLabel}</p>}
      <p>{conclusion?.summary ?? "Non évalué"}</p>
      {conclusion?.root_cause && <p className="mt-2">{diagnosisLabel} : {conclusion.root_cause}</p>}
      <p className="mt-2 text-muted">Confiance : {conclusion ? CONFIDENCE_LABEL[conclusion.confidence] : "Non évalué"}</p>
      <p className="text-muted">Impact non quantifié</p>
    </section>
    {result.error && <p role="alert" className="text-danger">{investigationFailure(result.error)}</p>}
    {result.hypotheses.map((h) => <section key={h.hypothesis_id} className="rounded-xl border border-border p-3">
      <h3 className="font-semibold">Hypothèse · {CONFIDENCE_LABEL[h.confidence]}</h3><p>{h.statement}</p><p className="mt-1 text-muted">{h.rationale}</p>
      <p className="mt-1 text-[10px] text-muted">Appuis : {h.supporting_evidence_ids.join(", ") || "Aucun"}</p>
      {h.contradictory_evidence_ids.length > 0 && <p className="text-[10px] text-muted">Contradictions : {h.contradictory_evidence_ids.join(", ")}</p>}
    </section>)}
    <InvestigationUncertainty result={result} />
    <InvestigationEvidence result={result} />
    <footer className="break-all text-[10px] text-muted">{result.operational_context?.site_name ?? `Site ${result.trigger.site_id}`} · {result.operational_context?.shift_name ?? "Poste non renseigné"}<br />Investigation {result.investigation_id}<br />{result.provider} / {result.model} · {result.graph_version}<br />Début {result.started_at} · Fin {result.completed_at ?? "En cours"}</footer>
  </div>
}

export function InvestigationUncertainty({ result }: { result: InvestigationResult }) {
  const conclusion = result.conclusion
  return <div className="mt-2 text-[11px]">    {(conclusion?.unresolved_uncertainties.length || result.requested_information.length || result.contradictions.length) ? <section>
      <h3 className="font-semibold">Incertitudes / informations manquantes</h3>
      <ul className="list-inside list-disc space-y-1">
        {conclusion?.unresolved_uncertainties.map((s, i) => <li key={`u${i}`}>{s}</li>)}
        {result.requested_information.map((r) => <li key={r.request_id}>{r.request_type} : {r.reason}</li>)}
        {result.contradictions.map((c, i) => <li key={`c${i}`}>Contradiction : {c.description} ({c.evidence_ids.join(", ")})</li>)}
      </ul>
    </section> : null}
</div>
}

export function InvestigationEvidence({ result }: { result: InvestigationResult }) {
  return <div className="text-[11px]">    <section><h3 className="mb-2 font-semibold">Éléments de preuve ({result.evidence.length})</h3>
      {result.evidence.length === 0 && <p>Éléments opérationnels indisponibles.</p>}
      {result.evidence.map((e) => <details key={e.evidence_id} className="mb-2 rounded-lg border border-border p-2">
        <summary className="cursor-pointer">{e.metric} · {e.kind} · {e.available ? "Disponible" : "Indisponible"}</summary>
        <div className="max-h-60 overflow-auto pt-2"><EvidenceValue evidence={e} /></div>
        <p className="mt-2 break-all text-[10px] text-muted">{e.evidence_id} · {e.source_service} · {e.observed_at ?? "Horodatage indisponible"}</p>
        {e.notes && <p className="text-muted">{e.notes}</p>}
      </details>)}
    </section>
</div>
}
