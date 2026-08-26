import { expect, it, vi } from "vitest"
import { result } from "@/test/aiFixtures"

it("navigation retains IDs rather than copied recommendations", async () => {
  const storage = new Map<string, string>()
  vi.stubGlobal("sessionStorage", { getItem: (k: string) => storage.get(k) ?? null, setItem: (k: string, v: string) => storage.set(k, v), removeItem: (k: string) => storage.delete(k) })
  const { useWorkspaceStore } = await import("./useWorkspaceStore")
  const store = useWorkspaceStore.getState()
  const alertsId = store.openWorkspace({ type: "alerts", context: { alertId: "alert-42", investigationId: result.investigation_id } })
  const actionsId = store.openWorkspace({ type: "actions", context: { alertId: "alert-42", investigationId: result.investigation_id } })
  store.activateTab(alertsId)
  store.activateTab(actionsId)
  const actions = useWorkspaceStore.getState().tabs.find((t) => t.id === actionsId)!
  expect(actions.context).toEqual({ alertId: "alert-42", investigationId: result.investigation_id })
  expect([...storage.values()].join()).toContain(result.investigation_id)
  expect([...storage.values()].join()).not.toContain(result.recommendation!.description)
})
