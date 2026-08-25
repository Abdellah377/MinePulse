import type { EquipmentFeatureProps } from "@/features/map/map.types"
import { equipmentPopupHtml } from "@/features/map/map.utils"

/** Compact hover tooltip content (HTML string for MapLibre Popup). */
export function equipmentTooltipHtml(props: EquipmentFeatureProps): string {
  return equipmentPopupHtml(props)
}
