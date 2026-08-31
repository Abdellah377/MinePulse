import { buildWorkspaceTitle } from "@/lib/workspace/titles"
import { useWorkspaceStore } from "@/lib/store/useWorkspaceStore"
import type { WorkspaceContext } from "@/lib/workspace/types"

export type MapFocusTarget = Pick<
  WorkspaceContext,
  "equipmentId" | "equipmentCode" | "zoneId" | "zoneName"
>

/** Reuse the keep-alive map tab and retarget it instead of opening a second Carte. */
export function openMapForTarget(target: MapFocusTarget): string {
  const context: WorkspaceContext = {
    equipmentId: target.equipmentId,
    equipmentCode: target.equipmentCode,
    zoneId: target.zoneId,
    zoneName: target.zoneName,
    mapFocusAt: Date.now(),
  }
  const store = useWorkspaceStore.getState()
  const maps = store.tabs.filter((tab) => tab.type === "map")
  const existing = maps.find((tab) => tab.id === store.activeTabId) ?? maps[0]
  if (existing) {
    store.patchTabContext(existing.id, context)
    store.setTabTitle(existing.id, buildWorkspaceTitle({ type: "map", context: { ...existing.context, ...context } }))
    store.activateTab(existing.id)
    return existing.id
  }
  return store.openWorkspace({ type: "map", context })
}
