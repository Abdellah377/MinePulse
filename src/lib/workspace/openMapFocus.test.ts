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
  const { resetWorkspaceStore, useWorkspaceStore } = await import("@/lib/store/useWorkspaceStore")
  resetWorkspaceStore()
  const { openMapForTarget } = await import("./openMapFocus")
  const id = openMapForTarget({ equipmentId: "TRK-001", equipmentCode: "TRK-001" })
  const tab = useWorkspaceStore.getState().tabs.find((t) => t.id === id)!
  expect(tab.type).toBe("map")
  expect(tab.context.equipmentId).toBe("TRK-001")
  expect(tab.context.equipmentCode).toBe("TRK-001")
})

it("reuses a contextual map for the same equipment and keeps Carte home distinct", async () => {
  const { resetWorkspaceStore, useWorkspaceStore } = await import("@/lib/store/useWorkspaceStore")
  resetWorkspaceStore()
  const { openMapForTarget } = await import("./openMapFocus")
  useWorkspaceStore.getState().openWorkspace({ type: "map" })
  const first = openMapForTarget({ equipmentId: "TRK-001", equipmentCode: "TRK-001" })
  const again = openMapForTarget({ equipmentId: "TRK-001", equipmentCode: "TRK-001" })
  const other = openMapForTarget({ equipmentId: "TRK-010", equipmentCode: "TRK-010" })
  expect(again).toBe(first)
  expect(other).not.toBe(first)
  const maps = useWorkspaceStore.getState().tabs.filter((t) => t.type === "map")
  expect(maps).toHaveLength(3)
  expect(maps.filter((t) => t.title === "Carte" || t.context._home)).toHaveLength(1)
})
