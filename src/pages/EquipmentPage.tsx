import { useParams, useNavigate } from "react-router-dom"
import { ArrowLeft } from "lucide-react"

import { Button } from "@/components/ui/button"
import { EquipmentDetailContent } from "@/components/equipment/EquipmentDetailContent"

export default function EquipmentPage() {
  const { id } = useParams()
  const navigate = useNavigate()

  return (
    <div className="mx-auto flex h-full max-w-3xl flex-col">
      <div className="flex items-center gap-2 border-b border-border px-4 py-2">
        <Button variant="ghost" size="sm" onClick={() => navigate(-1)}>
          <ArrowLeft className="size-3.5" />
          Retour
        </Button>
      </div>
      <div className="min-h-0 flex-1 overflow-hidden rounded-lg">
        {id && <EquipmentDetailContent equipmentId={id} />}
      </div>
    </div>
  )
}
