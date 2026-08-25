import { oemFamilyForView, resolveOemView } from "@/lib/oem/types"
import type { Equipment } from "@/lib/mock/types"
import type { OemView, WorkspaceContext } from "@/lib/workspace/types"

export function defaultOemEquipmentCode(equipment: Equipment[], preferred?: string): string | undefined {
  if (preferred && equipment.some((e) => e.code === preferred)) return preferred
  return equipment.find((e) => e.type === "haul_truck")?.code ?? equipment[0]?.code
}

export function oemOpenContext(view: OemView, equipmentCode?: string): WorkspaceContext {
  const resolved = resolveOemView(view)
  const family = oemFamilyForView(resolved)
  if (resolved === "connectivite") {
    return { oemFamily: family, oemView: resolved }
  }
  return { oemFamily: family, oemView: resolved, equipmentCode }
}
