/** Transport only. Diagnosis, confidence and recommendations belong to LangGraph. */
import { fetchJson, useApiMode } from "@/lib/api/client"
import type { InvestigationResult, InvestigationTriggerInput } from "@/lib/api/types/ai"

export type InvestigationScope = { site_id: number; source_record_id: string; shift_id?: number | null }

function requireApi() {
  if (!useApiMode) throw new Error("Investigations require API mode")
}

export const aiApi = {
  create(trigger: InvestigationTriggerInput): Promise<InvestigationResult> {
    requireApi()
    // V1 is synchronous, with bounded graph rounds. Never automatically retry POST.
    return fetchJson("/ai/investigations", { method: "POST", body: JSON.stringify(trigger), timeoutMs: 180_000 })
  },
  get(id: string): Promise<InvestigationResult> {
    requireApi()
    return fetchJson(`/ai/investigations/${encodeURIComponent(id)}`)
  },
  find(scope: InvestigationScope): Promise<InvestigationResult[]> {
    requireApi()
    const query = new URLSearchParams({ site_id: String(scope.site_id), source_record_id: scope.source_record_id })
    if (scope.shift_id != null) query.set("shift_id", String(scope.shift_id))
    return fetchJson(`/ai/investigations?${query}`)
  },
}
