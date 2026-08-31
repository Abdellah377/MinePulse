/** Transport only. Diagnosis, confidence and recommendations belong to LangGraph. */
import { ApiError, fetchJson, opsQueryString, useApiMode } from "@/lib/api/client"
import type { InvestigationResult, InvestigationTriggerInput } from "@/lib/api/types/ai"
import type { InvestigationDebugTrace } from "@/lib/api/types/aiDebug"
import type {
  DiscussionPostRequest,
  DiscussionThread,
  FollowUpStatusRequest,
  RecommendationDecisionRecord,
  RecommendationDecisionRequest,
  RecommendationDecisionView,
} from "@/lib/api/types/actionsIa"

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
  getDebug(id: string): Promise<InvestigationDebugTrace> {
    requireApi()
    return fetchJson(`/ai/investigations/${encodeURIComponent(id)}/debug`)
  },
  find(scope: InvestigationScope): Promise<InvestigationResult[]> {
    requireApi()
    const query = new URLSearchParams({ site_id: String(scope.site_id), source_record_id: scope.source_record_id })
    if (scope.shift_id != null) query.set("shift_id", String(scope.shift_id))
    return fetchJson(`/ai/investigations?${query}`)
  },
  getDecision(id: string): Promise<RecommendationDecisionView> {
    requireApi()
    return fetchJson(`/ai/investigations/${encodeURIComponent(id)}/decision`)
  },
  putDecision(id: string, body: RecommendationDecisionRequest): Promise<RecommendationDecisionRecord> {
    requireApi()
    return fetchJson(`/ai/investigations/${encodeURIComponent(id)}/decision`, {
      method: "PUT",
      body: JSON.stringify(body),
    })
  },
  patchFollowUp(id: string, body: FollowUpStatusRequest): Promise<RecommendationDecisionRecord> {
    requireApi()
    return fetchJson(`/ai/investigations/${encodeURIComponent(id)}/decision/follow-up`, {
      method: "PATCH",
      body: JSON.stringify(body),
    })
  },
  getDiscussion(id: string): Promise<DiscussionThread> {
    requireApi()
    return fetchJson(`/ai/investigations/${encodeURIComponent(id)}/discussion`)
  },
  postDiscussion(id: string, body: DiscussionPostRequest): Promise<DiscussionThread> {
    requireApi()
    return fetchJson(`/ai/investigations/${encodeURIComponent(id)}/discussion`, {
      method: "POST",
      body: JSON.stringify(body),
      timeoutMs: 60_000,
    })
  },
  listInbox(params?: { cursor?: string | null; limit?: number }, ctx?: { siteCode?: string; shiftId?: string }): Promise<import("./types/optimization").ActionsInboxPage> {
    requireApi()
    const extra: Record<string, string | boolean | undefined> = { limit: String(params?.limit ?? 20) }
    if (params?.cursor) extra.cursor = params.cursor
    return fetchJson(`/actions/inbox${opsQueryString(ctx, extra)}`)
  },
  getInboxDetail(alertId: string, ctx?: { siteCode?: string; shiftId?: string }): Promise<import("./types/optimization").ActionsInboxDetail> {
    requireApi()
    return fetchJson(`/actions/inbox/${encodeURIComponent(alertId)}${opsQueryString(ctx)}`)
  },
  putInboxDecision(alertId: string, body: RecommendationDecisionRequest, ctx?: { siteCode?: string; shiftId?: string }): Promise<RecommendationDecisionRecord> {
    requireApi()
    return fetchJson(`/actions/inbox/${encodeURIComponent(alertId)}/decision${opsQueryString(ctx)}`, {
      method: "PUT",
      body: JSON.stringify(body),
    })
  },
  createOptimizationRun(alertId: string, ctx?: { siteCode?: string; shiftId?: string }): Promise<import("./types/optimization").OptimizationRun> {
    requireApi()
    return fetchJson(`/optimization/runs${opsQueryString(ctx)}`, {
      method: "POST",
      body: JSON.stringify({ alert_id: alertId }),
    })
  },
  listOptimizationRuns(alertId: string): Promise<import("./types/optimization").OptimizationRun[]> {
    requireApi()
    return fetchJson(`/optimization/runs?alert_id=${encodeURIComponent(alertId)}`)
  },
}

export async function loadInvestigationDebug(id: string): Promise<InvestigationDebugTrace | null> {
  try {
    return await aiApi.getDebug(id)
  } catch (error) {
    if (error instanceof ApiError && (error.status === 403 || error.status === 404)) return null
    return null
  }
}
