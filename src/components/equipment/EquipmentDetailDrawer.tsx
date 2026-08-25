import { useNavigate } from "react-router-dom"

import { useUiStore } from "@/lib/store/useUiStore"
import { Sheet, SheetContent } from "@/components/ui/sheet"
import { EquipmentDetailContent } from "@/components/equipment/EquipmentDetailContent"

export function EquipmentDetailDrawer() {
  const equipmentId = useUiStore((s) => s.equipmentDrawerId)
  const close = useUiStore((s) => s.closeEquipmentDrawer)
  const navigate = useNavigate()

  return (
    <Sheet open={!!equipmentId} onOpenChange={(open) => !open && close()}>
      <SheetContent className="w-[460px] p-0 sm:max-w-[460px]">
        {equipmentId && (
          <EquipmentDetailContent
            equipmentId={equipmentId}
            showExpand
            onExpand={() => {
              navigate(`/equipement/${equipmentId}`)
              close()
            }}
          />
        )}
      </SheetContent>
    </Sheet>
  )
}
