import type { EquipmentType } from "@/lib/mock/types"
import { EQUIPMENT_ICON_SRC } from "@/lib/equipment-icons"
import { cn } from "@/lib/utils"

type Props = {
  type: EquipmentType
  className?: string
  title?: string
}

/** Side-profile flat equipment glyph (matches map markers). */
export function EquipmentTypeIcon({ type, className, title }: Props) {
  return (
    <img
      src={EQUIPMENT_ICON_SRC[type]}
      alt=""
      title={title}
      draggable={false}
      className={cn("size-full object-contain", className)}
    />
  )
}
