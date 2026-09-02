import { beforeEach, describe, expect, it, vi } from "vitest"

import { MODULE_HOME } from "@/lib/workspace/types"
import type { WorkspaceTab } from "@/lib/workspace/types"
import { isModuleHomeTab } from "@/lib/workspace/titles"

function tab(partial: Partial<WorkspaceTab> & Pick<WorkspaceTab, "id" | "type" | "title">): WorkspaceTab {
  return {
    module: "alertes",
    context: {},
    isPinned: false,
    isDirty: false,
    createdAt: 1,
    lastActivatedAt: 1,
    ...partial,
  }
}

beforeEach(() => {
  const storage = new Map<string, string>()
  vi.stubGlobal("sessionStorage", {
    getItem: (k: string) => storage.get(k) ?? null,
    setItem: (k: string, v: string) => storage.set(k, v),
    removeItem: (k: string) => storage.delete(k),
  })
})

function homeCount(type: WorkspaceTab["type"], tabs: WorkspaceTab[]) {
  return tabs.filter((item) => item.type === type && isModuleHomeTab(item)).length
}

describe("workspace home tab dedupe", () => {
  beforeEach(async () => {
    const { resetWorkspaceStore } = await import("./useWorkspaceStore")
    resetWorkspaceStore()
  })

  it("reuses Alertes IA home when the nav is clicked repeatedly", async () => {
    const { useWorkspaceStore } = await import("./useWorkspaceStore")
    const store = useWorkspaceStore.getState()
    for (let i = 0; i < 6; i += 1) store.openModuleHome("alertes")
    const tabs = useWorkspaceStore.getState().tabs
    expect(homeCount("alerts", tabs)).toBe(1)
    expect(tabs.filter((item) => item.type === "alerts")).toHaveLength(1)
  })

  it("reuses Carte, Film, Performance, OEM, and Paramètres homes", async () => {
    const { useWorkspaceStore } = await import("./useWorkspaceStore")
    const store = useWorkspaceStore.getState()
    for (let i = 0; i < 3; i += 1) {
      store.openWorkspace({ type: "map" })
      store.openWorkspace({ type: "timeline" })
      store.openModuleHome("performance")
      store.openModuleHome("oem")
      store.openModuleHome("parametres")
    }
    const tabs = useWorkspaceStore.getState().tabs
    expect(homeCount("map", tabs)).toBe(1)
    expect(homeCount("timeline", tabs)).toBe(1)
    expect(homeCount("performance", tabs)).toBe(1)
    expect(homeCount("oem", tabs)).toBe(1)
    expect(homeCount("settings", tabs)).toBe(1)
  })

  it("reuses Actions IA home", async () => {
    const { useWorkspaceStore } = await import("./useWorkspaceStore")
    const store = useWorkspaceStore.getState()
    for (let i = 0; i < 4; i += 1) store.openModuleHome("actions")
    expect(homeCount("actions", useWorkspaceStore.getState().tabs)).toBe(1)
  })

  it("lets a contextual Actions IA tab coexist with Actions IA home", async () => {
    const { useWorkspaceStore } = await import("./useWorkspaceStore")
    const store = useWorkspaceStore.getState()
    store.openModuleHome("actions")
    store.openWorkspace({ type: "actions", context: { equipmentId: "e9", equipmentCode: "TRK-009" } })
    store.openModuleHome("actions")
    const tabs = useWorkspaceStore.getState().tabs.filter((item) => item.type === "actions")
    expect(homeCount("actions", tabs)).toBe(1)
    expect(tabs).toHaveLength(2)
    expect(tabs.some((item) => item.context.equipmentCode === "TRK-009")).toBe(true)
  })

  it("lets different equipment contexts coexist", async () => {
    const { useWorkspaceStore } = await import("./useWorkspaceStore")
    const store = useWorkspaceStore.getState()
    store.openWorkspace({ type: "actions", context: { equipmentId: "e9", equipmentCode: "TRK-009" } })
    store.openWorkspace({ type: "actions", context: { equipmentId: "e15", equipmentCode: "TRK-015" } })
    const contextual = useWorkspaceStore.getState().tabs.filter((item) => item.type === "actions" && !isModuleHomeTab(item))
    expect(contextual).toHaveLength(2)
  })

  it("reuses the same contextual workspace according to existing dedupe semantics", async () => {
    const { useWorkspaceStore } = await import("./useWorkspaceStore")
    const store = useWorkspaceStore.getState()
    const first = store.openWorkspace({
      type: "actions",
      context: { equipmentId: "e9", equipmentCode: "TRK-009", investigationId: "inv-1" },
    })
    const second = store.openWorkspace({
      type: "actions",
      context: { equipmentId: "e9", equipmentCode: "TRK-009", investigationId: "inv-1" },
    })
    expect(second).toBe(first)
  })

  it("does not create a second home after incidental context is patched onto the home tab", async () => {
    const { useWorkspaceStore } = await import("./useWorkspaceStore")
    const store = useWorkspaceStore.getState()
    const homeId = store.openModuleHome("alertes")
    store.patchTabContext(homeId, { alertId: "alert-99", investigationId: "inv-99", equipmentCode: "TRK-009" })
    store.openModuleHome("alertes")
    store.openModuleHome("alertes")
    expect(homeCount("alerts", useWorkspaceStore.getState().tabs)).toBe(1)
  })

  it("closes and reopens a module home", async () => {
    const { useWorkspaceStore } = await import("./useWorkspaceStore")
    const store = useWorkspaceStore.getState()
    const first = store.openModuleHome("actions")
    expect(store.closeTab(first)).toBe(true)
    store.openModuleHome("actions")
    expect(homeCount("actions", useWorkspaceStore.getState().tabs)).toBe(1)
  })

  it("keeps duplicateTab copies distinct from the canonical home", async () => {
    const { useWorkspaceStore } = await import("./useWorkspaceStore")
    const store = useWorkspaceStore.getState()
    const homeId = store.openModuleHome("alertes")
    const copyId = store.duplicateTab(homeId)
    expect(copyId).toBeTruthy()
    store.openModuleHome("alertes")
    const tabs = useWorkspaceStore.getState().tabs.filter((item) => item.type === "alerts")
    expect(tabs).toHaveLength(2)
    expect(homeCount("alerts", tabs)).toBe(1)
  })
})

describe("duplicate home persistence hydration", () => {
  it("keeps the active home, contextual tabs, and pinned contextual tabs", async () => {
    const { normalizeDuplicateHomeTabs } = await import("./useWorkspaceStore")
    const tabs: WorkspaceTab[] = [
      tab({
        id: "home-old",
        type: "alerts",
        title: MODULE_HOME.alertes.title,
        module: "alertes",
        lastActivatedAt: 10,
      }),
      tab({
        id: "home-active",
        type: "alerts",
        title: MODULE_HOME.alertes.title,
        module: "alertes",
        lastActivatedAt: 5,
      }),
      tab({
        id: "actions-home",
        type: "actions",
        title: MODULE_HOME.actions.title,
        module: "actions",
        lastActivatedAt: 8,
      }),
      tab({
        id: "actions-trk",
        type: "actions",
        title: "Actions IA — TRK-009",
        module: "actions",
        context: { equipmentId: "e9", equipmentCode: "TRK-009" },
        lastActivatedAt: 20,
      }),
      tab({
        id: "pinned-trk",
        type: "map",
        title: "Carte — TRK-015",
        module: "alertes",
        context: { equipmentId: "e15", equipmentCode: "TRK-015" },
        isPinned: true,
        lastActivatedAt: 30,
      }),
    ]
    const normalized = normalizeDuplicateHomeTabs(tabs, "home-active")
    expect(normalized.tabs.map((item) => item.id).sort()).toEqual(
      ["actions-home", "actions-trk", "home-active", "pinned-trk"].sort(),
    )
    expect(normalized.activeTabId).toBe("home-active")
    expect(normalized.tabs.find((item) => item.id === "pinned-trk")?.isPinned).toBe(true)
    expect(normalized.tabs.find((item) => item.id === "actions-trk")).toBeTruthy()
    expect(normalized.tabs.every((item) => item.id !== "home-old")).toBe(true)
  })

  it("does not produce a blank workspace", async () => {
    const { normalizeDuplicateHomeTabs } = await import("./useWorkspaceStore")
    const normalized = normalizeDuplicateHomeTabs([], null)
    expect(normalized.tabs.length).toBeGreaterThan(0)
    expect(normalized.activeTabId).toBeTruthy()
  })
})
