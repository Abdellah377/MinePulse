import { buildWorkspaceTitle, contextDedupeKey, isModuleHomeTab, prepareWorkspaceContext } from "@/lib/workspace/titles"
import { useWorkspaceStore } from "@/lib/store/useWorkspaceStore"
import type { WorkspaceContext } from "@/lib/workspace/types"

export type MapFocusTarget = Pick<
  WorkspaceContext,
  "equipmentId" | "equipmentCode" | "zoneId" | "zoneName"
>

/** Reuse the same equipment/zone map workspace. Never convert the Carte home tab. */
export function openMapForTarget(target: MapFocusTarget): string {
  const context: WorkspaceContext = {
    equipmentId: target.equipmentId,
    equipmentCode: target.equipmentCode,
    zoneId: target.zoneId,
    zoneName: target.zoneName,
    mapFocusAt: Date.now(),
  }
  const store = useWorkspaceStore.getState()
  const key = contextDedupeKey("map", prepareWorkspaceContext("map", context))
  const existingId = store.dedupeIndex[key]
  const existing = existingId ? store.tabs.find((tab) => tab.id === existingId) : undefined
  if (existing && !isModuleHomeTab(existing)) {
    store.patchTabContext(existing.id, context)
    store.setTabTitle(existing.id, buildWorkspaceTitle({ type: "map", context: { ...existing.context, ...context } }))
    store.activateTab(existing.id)
    return existing.id
  }
  return store.openWorkspace({ type: "map", context })
}
