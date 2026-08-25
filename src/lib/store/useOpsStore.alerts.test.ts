import { beforeEach, describe, expect, it, vi } from "vitest"

import type { Alert } from "@/lib/mock/types"

const patchAlertMock = vi.fn()

vi.mock("@/lib/api/client", () => ({
  fetchBootstrap: vi.fn(),
  fetchOperationalSettings: vi.fn(),
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
})
