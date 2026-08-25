import { useNavigate } from "react-router-dom"
import { ChevronDown } from "lucide-react"

import { cn } from "@/lib/utils"
import { OEM_FAMILIES } from "@/lib/oem/types"
import { defaultOemEquipmentCode, oemOpenContext } from "@/lib/oem/openOem"
import { useSiteScopedEquipment } from "@/lib/store/useOpsStore"
import { useWorkspaceStore } from "@/lib/store/useWorkspaceStore"
import type { OemView } from "@/lib/workspace/types"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"

export function OemCatalogMenu({ active }: { active: boolean }) {
  const navigate = useNavigate()
  const openWorkspace = useWorkspaceStore((s) => s.openWorkspace)
  const equipment = useSiteScopedEquipment()

  function openReport(view: OemView) {
    const code = defaultOemEquipmentCode(equipment)
    openWorkspace({ type: "oem", context: oemOpenContext(view, code) })
    navigate("/oem")
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          title="OEM"
          className={cn(
            "flex h-11 shrink-0 items-center gap-0.5 border-b-2 px-2 text-[10px] font-semibold tracking-wider lg:px-2.5 lg:text-[11px]",
            active
              ? "border-white bg-black/10 text-white"
              : "border-transparent text-white/80 hover:bg-black/10 hover:text-white"
          )}
        >
          OEM
          <ChevronDown className="size-3 opacity-80" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="min-w-[240px]">
        <DropdownMenuLabel>Rapports OEM</DropdownMenuLabel>
        {OEM_FAMILIES.map((family) =>
          family.direct ? (
            <DropdownMenuItem key={family.id} onClick={() => openReport(family.views[0].id)}>
              {family.label}
            </DropdownMenuItem>
          ) : (
            <DropdownMenuSub key={family.id}>
              <DropdownMenuSubTrigger>{family.label}</DropdownMenuSubTrigger>
              <DropdownMenuSubContent className="min-w-[240px]">
                {family.views.map((v) => (
                  <DropdownMenuItem key={v.id} onClick={() => openReport(v.id)}>
                    {v.label}
                  </DropdownMenuItem>
                ))}
              </DropdownMenuSubContent>
            </DropdownMenuSub>
          )
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
