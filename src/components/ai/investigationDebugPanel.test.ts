import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { afterEach, beforeEach, expect, it, vi } from "vitest"
import { ApiError } from "@/lib/api/client"
import { aiApi, loadInvestigationDebug } from "@/lib/api/ai"
import { InvestigationDebugPanel } from "./InvestigationDebugPanel"
import type { InvestigationDebugTrace } from "@/lib/api/types/aiDebug"
import { result } from "@/test/aiFixtures"

vi.mock("@/lib/api/client", async (original) => ({ ...await original<typeof import("@/lib/api/client")>(), useApiMode: true }))

const trace: InvestigationDebugTrace = {
  investigation_id: result.investigation_id,
  graph_version: "1.3.0",
  provider: "mock",
  model: "mock-structured",
  stop_reason: "INCONCLUSIVE_AFTER_VALIDATION",
  events: [
    { event_id: "e1", sequence: 2, timestamp: "2026-08-29T10:00:02Z", stage: "analyze", event_type: "LLM_CALL", summary: "Structured LLM call (analyze)", duration_ms: 12, metadata: {} },
    { event_id: "e0", sequence: 1, timestamp: "2026-08-29T10:00:01Z", stage: "resolve_context", event_type: "CONTEXT_RESOLVED", summary: "Resolved SITE-A / shift 2", duration_ms: null, metadata: {} },
    { event_id: "e3", sequence: 3, timestamp: "2026-08-29T10:00:03Z", stage: "build_conclusion", event_type: "STATUS_DOWNGRADED", summary: "PROBABLE -> INCONCLUSIVE", duration_ms: null, metadata: { llm_diagnosis_status: "PROBABLE", final_diagnosis_status: "INCONCLUSIVE" } },
    { event_id: "e4", sequence: 4, timestamp: "2026-08-29T10:00:04Z", stage: "analyze", event_type: "PROVIDER_FAILURE", summary: "Investigation failed at analyze (ProviderTimeoutError)", duration_ms: null, metadata: { error_type: "ProviderTimeoutError" } },
  ],
  llm_proposed: { diagnosis_status: "PROBABLE", root_cause: "queue saturation", reliable_root_cause: false, confidence: "MEDIUM", supported_hypothesis_ids: ["hyp-1"] },
  backend_enforced: { diagnosis_status: "INCONCLUSIVE", root_cause: null, reliable_root_cause: false, confidence: "LOW", supported_hypothesis_ids: [] },
  validation_checks: [{ check_id: "DIAGNOSIS_CANNOT_CONCLUDE", passed: false, detail: "diagnosis.can_conclude is required for probable_eligible" }],
  coverage: { initial_count: 1, additional_requested: 0, available: 1, unavailable: 0, contradictory: 0, iterations: 1, max_iterations: 3, families: ["✓ shift_production"] },
  usage: { model: "mock-structured", request_count: 2, input_tokens: null, output_tokens: null, total_tokens: null },
  wall_durations_ms: { total: 40, llm: 20, evidence: 5, persist: 0, nodes: {} },
  trigger: { trigger_type: "PRODUCTION_DEVIATION" },
  recommendation: { action_type: "CONTINUE_MONITORING" },
  error: { stage: "analyze", error_type: "ProviderTimeoutError", message: "Investigation failed at analyze. Consult server logs." },
}

beforeEach(() => vi.stubGlobal("fetch", vi.fn()))
afterEach(() => vi.unstubAllGlobals())

it("hides the developer panel when no trace is available", () => {
  const html = renderToStaticMarkup(createElement(InvestigationDebugPanel, { investigationId: result.investigation_id, skipFetch: true }))
  expect(html).toBe("")
  expect(html).not.toContain("Trace technique")
})

it("renders timeline order, JSON, failed stage, and a PROBABLE to INCONCLUSIVE downgrade", () => {
  const html = renderToStaticMarkup(createElement(InvestigationDebugPanel, { investigationId: result.investigation_id, trace, skipFetch: true }))
  expect(html).toContain("Trace technique (dev)")
  const contextAt = html.indexOf("CONTEXT_RESOLVED")
  const llmAt = html.indexOf("LLM_CALL")
  expect(contextAt).toBeGreaterThan(-1)
  expect(llmAt).toBeGreaterThan(contextAt)
  expect(html).toContain("stop_reason")
  expect(html).toContain("View JSON")
  expect(html).toContain("Failed stage=analyze")
  expect(html).toContain("ProviderTimeoutError")
  expect(html).toContain("Downgrade: PROBABLE")
  expect(html).toContain("INCONCLUSIVE")
  expect(html).toContain("✓ shift_production")
})

it("loadInvestigationDebug hides 403/404 and returns a trace on 200", async () => {
  vi.mocked(fetch).mockResolvedValueOnce({ ok: false, status: 403, json: async () => ({ detail: { code: "AI_DEBUG_DISABLED" } }) } as Response)
  expect(await loadInvestigationDebug(result.investigation_id)).toBeNull()
  vi.mocked(fetch).mockResolvedValueOnce({ ok: false, status: 404, json: async () => ({}) } as Response)
  expect(await loadInvestigationDebug(result.investigation_id)).toBeNull()
  vi.mocked(fetch).mockResolvedValueOnce({ ok: true, json: async () => trace } as Response)
  expect(await loadInvestigationDebug(result.investigation_id)).toEqual(trace)
  expect(String(vi.mocked(fetch).mock.calls.at(-1)?.[0])).toContain("/debug")
})

it("getDebug is GET-only and preserves the disabled code", async () => {
  vi.mocked(fetch).mockResolvedValueOnce({ ok: false, status: 403, json: async () => ({ detail: { code: "AI_DEBUG_DISABLED" } }) } as Response)
  const error = await aiApi.getDebug(result.investigation_id).catch((item: unknown) => item)
  expect(error).toBeInstanceOf(ApiError)
  expect(error).toMatchObject({ code: "AI_DEBUG_DISABLED", status: 403 })
  expect(vi.mocked(fetch).mock.calls[0][1]?.method ?? "GET").not.toBe("POST")
})
