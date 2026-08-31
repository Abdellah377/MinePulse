import { afterEach, beforeEach, expect, it, vi } from "vitest"
import { ApiError, ApiNetworkError, ApiTimeoutError } from "./client"
import { aiApi } from "./ai"
import { result, trigger } from "@/test/aiFixtures"
vi.mock("@/lib/api/client", async (original) => ({ ...await original<typeof import("./client")>(), useApiMode: true }))
beforeEach(() => vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => result })))
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals() })

it("POST transports separate trigger semantics and preserves null payload values", async () => {
  expect(await aiApi.create(trigger)).toEqual(result)
  const [path, init] = vi.mocked(fetch).mock.calls[0]
  expect(String(path)).toContain("/ai/investigations")
  expect(init?.method).toBe("POST")
  expect(JSON.parse(String(init?.body))).toEqual(trigger)
})

it("preserves safe backend error codes, never arbitrary error bodies", async () => {
  vi.mocked(fetch).mockResolvedValue({ ok: false, status: 503, json: async () => ({ detail: { code: "AI_STORAGE_NOT_READY", message: "secret SQL" } }) } as Response)
  const error = await aiApi.create(trigger).catch((e: unknown) => e)
  expect(error).toBeInstanceOf(ApiError)
  expect(error).toMatchObject({ code: "AI_STORAGE_NOT_READY", status: 503 })
  expect(String(error)).not.toContain("secret")
})

it("distinguishes unreachable backend from the synchronous investigation timeout", async () => {
  vi.mocked(fetch).mockRejectedValueOnce(new TypeError("Failed to fetch"))
  await expect(aiApi.get(result.investigation_id)).rejects.toBeInstanceOf(ApiNetworkError)
  vi.useFakeTimers()
  vi.mocked(fetch).mockImplementation((_url, init) => new Promise((_resolve, reject) => {
    init?.signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")))
  }))
  const pending = aiApi.create(trigger)
  const assertion = expect(pending).rejects.toBeInstanceOf(ApiTimeoutError)
  await vi.advanceTimersByTimeAsync(179_999)
  expect(vi.mocked(fetch).mock.calls.at(-1)?.[1]?.signal?.aborted).toBe(false)
  await vi.advanceTimersByTimeAsync(1)
  await assertion
})
it("GET retrieves by UUID or by a site/shift-scoped alert ID", async () => {
  await aiApi.get(result.investigation_id)
  await aiApi.find({ site_id: 17, shift_id: 29, source_record_id: "alert-42" })
  expect(String(vi.mocked(fetch).mock.calls[0][0])).toContain(result.investigation_id)
  expect(String(vi.mocked(fetch).mock.calls[1][0])).toContain("site_id=17&source_record_id=alert-42&shift_id=29")
  expect(vi.mocked(fetch).mock.calls.every(([, init]) => !init?.method || init.method === "GET")).toBe(true)
})

it("decision GET/PUT and discussion GET do not start investigations", async () => {
  await aiApi.getDecision(result.investigation_id)
  await aiApi.putDecision(result.investigation_id, { decision_type: "ACCEPTED" })
  await aiApi.getDiscussion(result.investigation_id)
  expect(String(vi.mocked(fetch).mock.calls[0][0])).toContain("/decision")
  expect(vi.mocked(fetch).mock.calls[1][1]?.method).toBe("PUT")
  expect(String(vi.mocked(fetch).mock.calls[2][0])).toContain("/discussion")
  expect(vi.mocked(fetch).mock.calls.some(([, init]) => init?.method === "POST")).toBe(false)
})
