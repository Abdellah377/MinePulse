import { beforeEach, describe, expect, it, vi } from "vitest"
import { ApiError, ApiNetworkError, ApiTimeoutError } from "@/lib/api/client"
import { aiApi } from "@/lib/api/ai"
import { investigationKey, useInvestigationStore } from "./useInvestigationStore"
import { result, trigger } from "@/test/aiFixtures"

vi.mock("@/lib/api/ai", () => ({ aiApi: { create: vi.fn(), get: vi.fn(), find: vi.fn() } }))
const scope = { site_id: 17, shift_id: 29, source_record_id: "alert-42" }
const key = investigationKey(scope)

beforeEach(() => { vi.resetAllMocks(); useInvestigationStore.setState({ entries: {} }) })

describe("investigation lifecycle", () => {
  it("lookup on repeated renders never starts an LLM investigation", async () => {
    vi.mocked(aiApi.find).mockResolvedValue([])
    await Promise.all([useInvestigationStore.getState().lookup(scope), useInvestigationStore.getState().lookup(scope)])
    await useInvestigationStore.getState().lookup(scope)
    expect(aiApi.find).toHaveBeenCalledTimes(1)
    expect(aiApi.create).not.toHaveBeenCalled()
    expect(useInvestigationStore.getState().entries[key].phase).toBe("absent")
  })
  it("deduplicates simultaneous manual starts and caches the persisted UUID", async () => {
    vi.mocked(aiApi.find).mockResolvedValue([])
    vi.mocked(aiApi.create).mockResolvedValue(result)
    await Promise.all([useInvestigationStore.getState().start(trigger), useInvestigationStore.getState().start(trigger)])
    await useInvestigationStore.getState().start(trigger)
    expect(aiApi.create).toHaveBeenCalledTimes(1)
    expect(useInvestigationStore.getState().entries[key].result).toEqual(result)
    expect(useInvestigationStore.getState().entries[result.investigation_id].result).toEqual(result)
  })
  it("retries a persisted FAILED investigation instead of returning the stale failure", async () => {
    const failed = { ...result, status: "FAILED" as const, conclusion: null, recommendation: null, error: { stage: "analyze", error_type: "ProviderTimeoutError", message: "safe" } }
    const recovered = { ...result, investigation_id: "11111111-1111-4111-8111-111111111111" }
    vi.mocked(aiApi.find).mockResolvedValue([failed])
    vi.mocked(aiApi.create).mockResolvedValue(recovered)
    await useInvestigationStore.getState().start(trigger)
    expect(aiApi.create).not.toHaveBeenCalled()
    expect(useInvestigationStore.getState().entries[key].result?.status).toBe("FAILED")
    await useInvestigationStore.getState().start(trigger, { retryFailed: true })
    expect(aiApi.create).toHaveBeenCalledTimes(1)
    expect(useInvestigationStore.getState().entries[key].result?.investigation_id).toBe(recovered.investigation_id)
  })
  it("provider failure does not fabricate a result", async () => {
    vi.mocked(aiApi.find).mockResolvedValue([])
    vi.mocked(aiApi.create).mockRejectedValue(new ApiError(503, "do not expose secret diagnostic", "AI_PROVIDER_NOT_CONFIGURED"))
    await useInvestigationStore.getState().start(trigger)
    const entry = useInvestigationStore.getState().entries[key]
    expect(entry.phase).toBe("error")
    expect(entry.error).toContain("Fournisseur IA")
    expect(entry.error).not.toContain("secret")
    expect(entry.result).toBeUndefined()
  })
  it("does not retry an ambiguous POST timeout; read-only recovery can retrieve its result", async () => {
    vi.mocked(aiApi.find).mockResolvedValue([])
    vi.mocked(aiApi.create).mockRejectedValue(new ApiTimeoutError())
    await useInvestigationStore.getState().start(trigger)
    await useInvestigationStore.getState().start(trigger)
    expect(aiApi.create).toHaveBeenCalledTimes(1)
    expect(useInvestigationStore.getState().entries[key].creationUncertain).toBe(true)
    await useInvestigationStore.getState().lookup(scope, true)
    expect(useInvestigationStore.getState().entries[key].creationUncertain).toBe(true)
    vi.mocked(aiApi.find).mockResolvedValue([result])
    await useInvestigationStore.getState().lookup(scope, true)
    expect(useInvestigationStore.getState().entries[key].result).toEqual(result)
  })
  it("separates site/shift contexts and reports retrieval failure", async () => {
    expect(investigationKey({ ...scope, site_id: 18 })).not.toBe(key)
    expect(investigationKey({ ...scope, shift_id: 30 })).not.toBe(key)
    vi.mocked(aiApi.get).mockRejectedValue(new ApiError(404, "missing"))
    await useInvestigationStore.getState().retrieve(result.investigation_id)
    expect(useInvestigationStore.getState().entries[result.investigation_id].error).toContain("introuvable")
  })

  it("reuses a completed investigation without a second POST", async () => {
    vi.mocked(aiApi.find).mockResolvedValue([])
    vi.mocked(aiApi.create).mockResolvedValue(result)
    await useInvestigationStore.getState().start(trigger)
    await useInvestigationStore.getState().start(trigger)
    expect(aiApi.create).toHaveBeenCalledTimes(1)
  })

  it("lookup does not clobber an in-flight start with absent", async () => {
    let releaseFind!: (value: typeof result[]) => void
    let releaseCreate!: (value: typeof result) => void
    let findCalls = 0
    vi.mocked(aiApi.find).mockImplementation(() => {
      findCalls += 1
      if (findCalls === 1) return new Promise((resolve) => { releaseFind = resolve })
      return Promise.resolve([])
    })
    vi.mocked(aiApi.create).mockImplementation(() => new Promise((resolve) => { releaseCreate = resolve }))
    const lookupP = useInvestigationStore.getState().lookup(scope)
    await vi.waitFor(() => expect(useInvestigationStore.getState().entries[key].phase).toBe("loading"))
    const startP = useInvestigationStore.getState().start(trigger)
    await vi.waitFor(() => expect(useInvestigationStore.getState().entries[key].phase).toBe("running"))
    releaseFind([])
    await lookupP
    expect(useInvestigationStore.getState().entries[key].phase).toBe("running")
    expect(aiApi.create).toHaveBeenCalledTimes(1)
    releaseCreate(result)
    await startP
    expect(useInvestigationStore.getState().entries[key].result).toEqual(result)
    expect(useInvestigationStore.getState().entries[key].phase).toBe("ready")
  })

  it("lookup network error does not clobber an in-flight start", async () => {
    let rejectFind!: (error: ApiNetworkError) => void
    let releaseCreate!: (value: typeof result) => void
    vi.mocked(aiApi.find).mockImplementationOnce(() => new Promise((_, reject) => { rejectFind = reject }))
    vi.mocked(aiApi.find).mockResolvedValue([])
    vi.mocked(aiApi.create).mockImplementation(() => new Promise((resolve) => { releaseCreate = resolve }))
    const lookupP = useInvestigationStore.getState().lookup(scope)
    await vi.waitFor(() => expect(useInvestigationStore.getState().entries[key].phase).toBe("loading"))
    const startP = useInvestigationStore.getState().start(trigger)
    await vi.waitFor(() => expect(useInvestigationStore.getState().entries[key].phase).toBe("running"))
    rejectFind(new ApiNetworkError())
    await lookupP
    expect(useInvestigationStore.getState().entries[key].phase).toBe("running")
    releaseCreate(result)
    await startP
    expect(useInvestigationStore.getState().entries[key].phase).toBe("ready")
  })

  it("shows running until POST settles and cannot launch a second investigation", async () => {
    vi.mocked(aiApi.find).mockResolvedValue([])
    let finish!: (value: typeof result) => void
    vi.mocked(aiApi.create).mockImplementation(() => new Promise((resolve) => { finish = resolve }))
    const pending = useInvestigationStore.getState().start(trigger)
    await vi.waitFor(() => expect(useInvestigationStore.getState().entries[key].phase).toBe("running"))
    const duplicate = useInvestigationStore.getState().start(trigger)
    finish(result)
    await Promise.all([pending, duplicate])
    expect(aiApi.create).toHaveBeenCalledTimes(1)
    expect(useInvestigationStore.getState().entries[key].result).toEqual(result)
  })

  it.each([
    [new ApiError(503, "private", "AI_STORAGE_NOT_READY"), "migrations"],
    [new ApiError(503, "private", "AI_PROVIDER_NOT_CONFIGURED"), "AI_PROVIDER"],
    [new ApiError(500, "private", "AI_PERSISTENCE_FAILED"), "enregistrement"],
    [new ApiNetworkError(), "injoignable"],
    [new ApiTimeoutError(), "Délai"],
    [new ApiError(422, "private"), "invalide"],
  ])("reports distinct safe failures", async (error, label) => {
    vi.mocked(aiApi.find).mockRejectedValue(error)
    await useInvestigationStore.getState().lookup(scope)
    const entry = useInvestigationStore.getState().entries[key]
    expect(entry.error).toContain(label)
    expect(entry.error).not.toContain("private")
    expect(entry.result).toBeUndefined()
  })

  it("keeps an already persisted result visible if refresh fails", async () => {
    vi.mocked(aiApi.find).mockResolvedValue([result])
    await useInvestigationStore.getState().lookup(scope)
    vi.mocked(aiApi.find).mockRejectedValue(new ApiNetworkError())
    await useInvestigationStore.getState().lookup(scope, true)
    expect(useInvestigationStore.getState().entries[key].result).toEqual(result)
    expect(useInvestigationStore.getState().entries[key].error).toContain("injoignable")
  })
})
