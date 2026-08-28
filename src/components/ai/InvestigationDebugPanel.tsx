import { useEffect, useMemo, useState } from "react"
import { loadInvestigationDebug } from "@/lib/api/ai"
import type { DebugEvent, InvestigationDebugTrace } from "@/lib/api/types/aiDebug"

const SECTIONS: { id: string; title: string; pick: (trace: InvestigationDebugTrace) => unknown }[] = [
  { id: "trigger", title: "Trigger", pick: (trace) => trace.trigger },
  { id: "graph", title: "Graph", pick: (trace) => ({ graph_version: trace.graph_version, provider: trace.provider, model: trace.model, stop_reason: trace.stop_reason }) },
  { id: "evidence", title: "Evidence", pick: (trace) => eventsOf(trace, "INITIAL_EVIDENCE_GATHERED") },
  { id: "requests", title: "Requests", pick: (trace) => eventsOf(trace, "ADDITIONAL_EVIDENCE_REQUESTED") },
  { id: "tools", title: "Tools", pick: (trace) => eventsOf(trace, "TOOL_COMPLETED") },
  { id: "hypotheses", title: "Hypotheses", pick: (trace) => eventsOf(trace, "HYPOTHESIS_EVALUATED") },
  { id: "contradictions", title: "Contradictions", pick: (trace) => trace.coverage.contradictory },
  { id: "validation", title: "Validation", pick: (trace) => trace.validation_checks },
  { id: "conclusion", title: "Conclusion", pick: (trace) => ({ llm_proposed: trace.llm_proposed, backend_enforced: trace.backend_enforced, downgrades: eventsOf(trace, "STATUS_DOWNGRADED") }) },
  { id: "recommendation", title: "Recommendation", pick: (trace) => trace.recommendation },
  { id: "errors", title: "Errors", pick: (trace) => trace.error ?? eventsOf(trace, "PROVIDER_FAILURE", "INVESTIGATION_FAILED") },
  { id: "coverage", title: "Coverage", pick: (trace) => trace.coverage },
  { id: "usage", title: "Usage", pick: (trace) => ({ usage: trace.usage, wall_durations_ms: trace.wall_durations_ms }) },
]

function eventsOf(trace: InvestigationDebugTrace, ...types: DebugEvent["event_type"][]) {
  return trace.events.filter((event) => types.includes(event.event_type))
}

function DebugJson({ value }: { value: unknown }) {
  return (
    <details className="mt-1">
      <summary className="cursor-pointer text-muted-2">View JSON</summary>
      <pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap break-all text-muted">{JSON.stringify(value, null, 2)}</pre>
    </details>
  )
}

export function InvestigationDebugPanel({
  investigationId,
  trace: injected,
  skipFetch = false,
}: {
  investigationId?: string | null
  trace?: InvestigationDebugTrace | null
  skipFetch?: boolean
}) {
  const [trace, setTrace] = useState<InvestigationDebugTrace | null>(injected ?? null)
  useEffect(() => {
    if (injected !== undefined) {
      setTrace(injected)
      return
    }
    if (skipFetch || !investigationId) {
      setTrace(null)
      return
    }
    let cancelled = false
    void loadInvestigationDebug(investigationId).then((next) => {
      if (!cancelled) setTrace(next)
    })
    return () => {
      cancelled = true
    }
  }, [investigationId, injected, skipFetch])
  const timeline = useMemo(
    () => [...(trace?.events ?? [])].sort((a, b) => a.sequence - b.sequence),
    [trace],
  )
  if (!trace) return null
  const failed = eventsOf(trace, "PROVIDER_FAILURE", "INVESTIGATION_FAILED")[0]
  const downgrade = eventsOf(trace, "STATUS_DOWNGRADED")[0]
  return (
    <details className="mt-4 rounded-md border border-dashed border-border bg-surface-2/40 p-2 font-mono text-[10px] text-muted">
      <summary className="cursor-pointer text-[10px] font-medium uppercase tracking-wide text-muted-2">Trace technique (dev)</summary>
      <p className="mt-2 text-muted-2">Stop: {trace.stop_reason ?? "—"} · {trace.provider}/{trace.model} · {trace.graph_version}</p>
      {failed && (
        <p className="mt-1 text-danger">
          Failed stage={String(trace.error?.stage ?? failed.stage)} type={String(trace.error?.error_type ?? failed.metadata.error_type ?? failed.event_type)} {String(trace.error?.message ?? failed.summary)}
        </p>
      )}
      {downgrade && <p className="mt-1">Downgrade: {downgrade.summary}</p>}
      {trace.coverage.families.length > 0 && (
        <p className="mt-1">Coverage: {trace.coverage.families.join(" · ")}</p>
      )}
      <section className="mt-2">
        <p className="font-medium text-muted-2">Timeline</p>
        <ol className="mt-1 space-y-0.5">
          {timeline.map((event) => (
            <li key={event.event_id}>
              <span className="text-muted-2">{event.timestamp}</span> {event.event_type} — {event.summary}
            </li>
          ))}
        </ol>
      </section>
      {SECTIONS.map((section) => {
        const value = section.pick(trace)
        return (
          <section key={section.id} className="mt-2 border-t border-border/60 pt-1">
            <p className="font-medium text-muted-2">{section.title}</p>
            <DebugJson value={value} />
          </section>
        )
      })}
    </details>
  )
}
