import { useEffect, useMemo } from "react"
import { useNavigate } from "react-router-dom"
import {
  AlertTriangle,
  MapIcon,
  Film as FilmIcon,
  BarChart3,
  Sparkles,
  Settings,
  Cpu,
  User,
} from "lucide-react"

import { OEM_FAMILIES } from "@/lib/oem/types"
import { defaultOemEquipmentCode, oemOpenContext } from "@/lib/oem/openOem"
import { useOpsStore, useSiteScopedEquipment } from "@/lib/store/useOpsStore"
import { useUiStore } from "@/lib/store/useUiStore"
import { useWorkspaceStore } from "@/lib/store/useWorkspaceStore"
import type { WorkspaceType } from "@/lib/workspace/types"
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
  CommandShortcut,
} from "@/components/ui/command"
import { EquipmentTypeIcon } from "@/components/equipment/EquipmentTypeIcon"

const PAGES: { type: WorkspaceType; label: string; icon: typeof AlertTriangle; path: string }[] = [
  { type: "alerts", label: "Alertes IA", icon: AlertTriangle, path: "/alertes" },
  { type: "actions", label: "Actions IA", icon: Sparkles, path: "/actions" },
  { type: "map", label: "Carte", icon: MapIcon, path: "/alertes" },
  { type: "timeline", label: "Film", icon: FilmIcon, path: "/alertes" },
  { type: "performance", label: "Performance", icon: BarChart3, path: "/performance" },
  { type: "oem", label: "OEM", icon: Cpu, path: "/oem" },
  { type: "settings", label: "Paramètres", icon: Settings, path: "/parametres" },
]

export function CommandPalette() {
  const open = useUiStore((s) => s.commandOpen)
  const setOpen = useUiStore((s) => s.setCommandOpen)
  const openEquipmentDrawer = useUiStore((s) => s.openEquipmentDrawer)
  const openWorkspace = useWorkspaceStore((s) => s.openWorkspace)
  const navigate = useNavigate()

  const equipment = useOpsStore((s) => s.equipment)
  const oemEquipment = useSiteScopedEquipment()
  const operators = useOpsStore((s) => s.operators)

  useEffect(() => {
    function handler(e: KeyboardEvent) {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault()
        setOpen(!open)
      }
    }
    window.addEventListener("keydown", handler)
    return () => window.removeEventListener("keydown", handler)
  }, [open, setOpen])

  const equipmentItems = useMemo(() => equipment.slice(0, 200), [equipment])

  return (
    <CommandDialog open={open} onOpenChange={setOpen}>
      <CommandInput placeholder="Aller à une page, un engin, un conducteur…" />
      <CommandList>
        <CommandEmpty>Aucun résultat.</CommandEmpty>
        <CommandGroup heading="Espaces">
          {PAGES.map((p) => (
            <CommandItem
              key={p.type}
              value={p.label}
              onSelect={() => {
                openWorkspace({ type: p.type })
                navigate(p.path)
                setOpen(false)
              }}
            >
              <p.icon className="size-3.5 text-muted-2" />
              {p.label}
            </CommandItem>
          ))}
        </CommandGroup>
        <CommandSeparator />
        <CommandGroup heading="OEM">
          {OEM_FAMILIES.flatMap((f) =>
            f.views.map((v) => (
              <CommandItem
                key={v.id}
                value={`OEM ${f.label} ${v.label}`}
                onSelect={() => {
                  const code = defaultOemEquipmentCode(oemEquipment)
                  openWorkspace({ type: "oem", context: oemOpenContext(v.id, code) })
                  navigate("/oem")
                  setOpen(false)
                }}
              >
                <Cpu className="size-3.5 text-muted-2" />
                {v.label}
              </CommandItem>
            ))
          )}
        </CommandGroup>
        <CommandSeparator />
        <CommandGroup heading="Engins">
          {equipmentItems.map((eq) => (
            <CommandItem
              key={eq.id}
              value={`${eq.code} ${eq.model}`}
              onSelect={() => {
                openEquipmentDrawer(eq.id)
                setOpen(false)
              }}
            >
              <span className="flex size-4 shrink-0 items-center justify-center">
                <EquipmentTypeIcon type={eq.type} className="size-4" />
              </span>
              <span>{eq.code}</span>
              <span className="text-muted-2">{eq.model}</span>
              <CommandShortcut>{eq.type.replace("_", " ")}</CommandShortcut>
            </CommandItem>
          ))}
        </CommandGroup>
        <CommandSeparator />
        <CommandGroup heading="Conducteurs">
          {operators.slice(0, 50).map((op) => (
            <CommandItem key={op.id} value={op.name} onSelect={() => setOpen(false)}>
              <User className="size-3.5 text-muted-2" />
              {op.name}
              <CommandShortcut>{op.badgeId}</CommandShortcut>
            </CommandItem>
          ))}
        </CommandGroup>
      </CommandList>
    </CommandDialog>
  )
}
