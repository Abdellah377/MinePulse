import { useApiMode } from "@/lib/api/client"

/** Completed-shift contribution in tonnes, or null when unknown. */
export function equipmentContributionTons(eq: {
  payloadTons: number | null
  capacityTons: number | null
  tripsThisShift: number
}): number | null {
  if (!useApiMode) {
    if (eq.capacityTons == null) return null
    return eq.capacityTons * eq.tripsThisShift * 0.94
  }
  // API DTO has no completed-production tonnes per equipment. Current payload is
  // instantaneous load, not hauled-this-shift — never invent from capacity.
  return null
}

export function formatEquipmentContribution(eq: {
  payloadTons: number | null
  capacityTons: number | null
  tripsThisShift: number
}): string {
  const tons = equipmentContributionTons(eq)
  return tons == null ? "—" : `${tons.toFixed(0)} t`
}
