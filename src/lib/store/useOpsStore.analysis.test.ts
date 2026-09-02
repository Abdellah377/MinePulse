import { beforeEach, describe, expect, it, vi } from "vitest"

vi.mock("@/lib/api/client", () => ({
  fetchBootstrap: vi.fn(),
  fetchOperationalSettings: vi.fn(),
  fetchActiveAlertCount: vi.fn(async () => ({ activeCount: 0 })),
  patchAlert: vi.fn(),
  patchOperationalSettings: vi.fn(),
  useApiMode: true,
}))

describe("analysis filters vs live shift context", () => {
  beforeEach(async () => {
    const { useOpsStore } = await import("./useOpsStore")
    const { useAlertFeedStore } = await import("./useAlertFeedStore")
    useAlertFeedStore.getState().reset()
    useAlertFeedStore.setState({
      orderedIds: ["a1"],
      byId: {
        a1: {
          id: "a1",
          title: "Live",
          description: "",
          severity: "warning",
          status: "new",
          category: "X",
          source: "RULE",
          createdAt: 1,
          updatedAt: 1,
          assignedTo: null,
          resolution: null,
          equipmentId: null,
          zoneId: null,
          location: "",
        },
      },
      activeCount: 1,
    })
    useOpsStore.setState({
      selectedSiteId: "SITE-B",
      selectedShiftId: "shift-9",
      periodFrom: "2026-01-30",
      periodTo: "2026-01-30",
      selectedPoste: "all",
      analysisPeriodTouched: false,
      equipment: [{ id: "TRK-010" } as never],
      alerts: [],
      simNowIso: "2026-01-30T10:00:00.000Z",
    })
  })

  it("changing period or poste does not empty live scope or reset the alert feed", async () => {
    const { useOpsStore } = await import("./useOpsStore")
    const { useAlertFeedStore } = await import("./useAlertFeedStore")
    useOpsStore.getState().setPeriodRange("2026-01-28", "2026-01-30")
    useOpsStore.getState().setSelectedPoste("nuit")
    expect(useOpsStore.getState().equipment).toHaveLength(1)
    expect(useOpsStore.getState().selectedShiftId).toBe("shift-9")
    expect(useOpsStore.getState().selectedPoste).toBe("nuit")
    expect(useAlertFeedStore.getState().orderedIds).toEqual(["a1"])
  })

  it("defaults the analysis period from simNow on hydrate until the operator changes it", async () => {
    const { useOpsStore } = await import("./useOpsStore")
    useOpsStore.setState({
      analysisPeriodTouched: false,
      periodFrom: "2026-09-01",
      periodTo: "2026-09-01",
      apiBootstrapped: true,
    })
    useOpsStore.getState().hydrateWorld({ simNow: "2026-01-29T08:00:00.000Z" })
    expect(useOpsStore.getState().periodFrom).toBe("2026-01-29")
    expect(useOpsStore.getState().periodTo).toBe("2026-01-29")
    useOpsStore.getState().setPeriodRange("2026-01-28", "2026-01-28")
    useOpsStore.getState().hydrateWorld({ simNow: "2026-01-30T08:00:00.000Z" })
    expect(useOpsStore.getState().periodFrom).toBe("2026-01-28")
  })

  it("reset restores operational today and Tous les postes", async () => {
    const { useOpsStore } = await import("./useOpsStore")
    useOpsStore.getState().setSelectedPoste("matin")
    useOpsStore.getState().setPeriodRange("2026-01-28", "2026-01-29")
    useOpsStore.getState().resetAnalysisFilters()
    expect(useOpsStore.getState().selectedPoste).toBe("all")
    expect(useOpsStore.getState().periodFrom).toBe("2026-01-30")
    expect(useOpsStore.getState().periodTo).toBe("2026-01-30")
    expect(useOpsStore.getState().analysisPeriodTouched).toBe(false)
  })

  it("snaps a stale selected shift to the poste that contains simNow", async () => {
    const { useOpsStore } = await import("./useOpsStore")
    useOpsStore.setState({
      apiBootstrapped: true,
      selectedShiftId: "shift-8",
      simNowIso: "2026-01-29T10:02:00.000Z",
      shifts: [
        { id: "shift-1", name: "Matin", startHour: 6, endHour: 14, windowStart: "2026-01-29T06:00:00.000Z", windowEnd: "2026-01-29T14:00:00.000Z" },
        { id: "shift-8", name: "Après-midi", startHour: 14, endHour: 22, windowStart: "2026-01-31T14:00:00.000Z", windowEnd: "2026-01-31T22:00:00.000Z" },
      ],
    })
    useOpsStore.getState().hydrateWorld({
      simNow: "2026-01-29T10:02:00.000Z",
      activeShiftId: "shift-1",
      shifts: [
        { id: "shift-1", name: "Matin", startHour: 6, endHour: 14, windowStart: "2026-01-29T06:00:00.000Z", windowEnd: "2026-01-29T14:00:00.000Z" },
        { id: "shift-8", name: "Après-midi", startHour: 14, endHour: 22, windowStart: "2026-01-31T14:00:00.000Z", windowEnd: "2026-01-31T22:00:00.000Z" },
      ],
    })
    expect(useOpsStore.getState().selectedShiftId).toBe("shift-1")
  })
})
