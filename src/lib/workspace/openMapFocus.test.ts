import { beforeEach, expect, it, vi } from "vitest"

beforeEach(() => {
  const storage = new Map<string, string>()
  vi.stubGlobal("sessionStorage", {
    getItem: (k: string) => storage.get(k) ?? null,
    setItem: (k: string, v: string) => storage.set(k, v),
    removeItem: (k: string) => storage.delete(k),
  })
})

it("preserves equipment identity when opening the map from an alert or inspector", async () => {
  const { useWorkspaceStore } = await import("@/lib/store/useWorkspaceStore")
  const { openMapForTarget } = await import("./openMapFocus")
  const id = openMapForTarget({ equipmentId: "TRK-001", equipmentCode: "TRK-001" })
  const tab = useWorkspaceStore.getState().tabs.find((t) => t.id === id)!
  expect(tab.type).toBe("map")
  expect(tab.context.equipmentId).toBe("TRK-001")
  expect(tab.context.equipmentCode).toBe("TRK-001")
})

it("retargets an already mounted map instead of leaving the previous camera target", async () => {
  const { useWorkspaceStore } = await import("@/lib/store/useWorkspaceStore")
  const { openMapForTarget } = await import("./openMapFocus")
  const first = openMapForTarget({ equipmentId: "TRK-001", equipmentCode: "TRK-001" })
  const second = openMapForTarget({ equipmentId: "TRK-010", equipmentCode: "TRK-010" })
  expect(second).toBe(first)
  const tab = useWorkspaceStore.getState().tabs.find((t) => t.id === first)!
  expect(tab.context.equipmentId).toBe("TRK-010")
  expect(typeof tab.context.mapFocusAt).toBe("number")
  expect(useWorkspaceStore.getState().tabs.filter((t) => t.type === "map")).toHaveLength(1)
})
