import { beforeEach, describe, expect, it, vi } from "vitest"

import type { Alert } from "@/lib/mock/types"

const patchAlertMock = vi.fn()

vi.mock("@/lib/api/client", () => ({
  fetchBootstrap: vi.fn(),
  fetchOperationalSettings: vi.fn(),
  fetchActiveAlertCount: vi.fn(async () => ({ activeCount: 0 })),
  patchAlert: patchAlertMock,
  patchOperationalSettings: vi.fn(),
  useApiMode: true,
}))

const baseAlert: Alert = {
  id: "alert-1",
  severity: "warning",
  status: "new",
  title: "Test",
  description: "Test",
  equipmentId: "TR-01",
  zoneId: null,
  location: "Site",
  category: "TEST",
  createdAt: 1,
  updatedAt: 1,
  assignedTo: null,
  resolution: null,
}

describe("updateAlertStatus in API mode", () => {
  beforeEach(async () => {
    vi.clearAllMocks()
    const { useOpsStore } = await import("./useOpsStore")
    useOpsStore.setState({
      alerts: [baseAlert],
      selectedSiteId: "SITE-B",
      selectedShiftId: "shift-9",
      apiPollError: null,
    })
  })

  it("updates Zustand only from the authoritative PATCH response", async () => {
    const { useOpsStore } = await import("./useOpsStore")
    const updated: Alert = {
      ...baseAlert,
      status: "assigned",
      assignedTo: "Régulateur",
      updatedAt: 2,
    }
    let resolvePatch: (alert: Alert) => void = () => undefined
    const patchPromise = new Promise<Alert>((resolve) => {
      resolvePatch = resolve
    })
    patchAlertMock.mockReturnValueOnce(patchPromise)

    useOpsStore.getState().updateAlertStatus("alert-1", "assigned", "Régulateur")

    expect(useOpsStore.getState().alerts[0]).toEqual(baseAlert)
    expect(patchAlertMock).toHaveBeenCalledWith(
      "alert-1",
      { status: "assigned", actor_label: "Régulateur" },
      { siteCode: "SITE-B", shiftId: "shift-9" }
    )

    resolvePatch(updated)
    await patchPromise
    await Promise.resolve()

    expect(useOpsStore.getState().alerts[0]).toEqual(updated)
    expect(useOpsStore.getState().apiPollError).toBeNull()
  })

  it("resolved PATCH keeps the row in history and uses backend activeCount", async () => {
    const { useOpsStore } = await import("./useOpsStore")
    const { useAlertFeedStore } = await import("./useAlertFeedStore")
    const { fetchActiveAlertCount } = await import("@/lib/api/client")
    useAlertFeedStore.getState().reset()
    useAlertFeedStore.getState().setActiveCount(10)
    patchAlertMock.mockResolvedValueOnce({ ...baseAlert, status: "resolved", updatedAt: 2 })
    vi.mocked(fetchActiveAlertCount).mockResolvedValueOnce({ activeCount: 9 })

    await useOpsStore.getState().updateAlertStatus("alert-1", "resolved", "Chef de poste")

    expect(useAlertFeedStore.getState().activeCount).toBe(9)
    expect(useAlertFeedStore.getState().byId["alert-1"].status).toBe("resolved")
    expect(useAlertFeedStore.getState().orderedIds).toContain("alert-1")
  })
})
