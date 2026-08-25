import { useRef, useState } from "react"
import {
  AlertTriangle,
  Map as MapIcon,
  Film,
  BarChart3,
  Sparkles,
  Settings,
  Cpu,
  X,
  Pin,
  ChevronDown,
} from "lucide-react"

import { cn } from "@/lib/utils"
import { useWorkspaceStore } from "@/lib/store/useWorkspaceStore"
import type { WorkspaceTab, WorkspaceType } from "@/lib/workspace/types"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"

const TYPE_ICON: Record<WorkspaceType, typeof MapIcon> = {
  alerts: AlertTriangle,
  map: MapIcon,
  timeline: Film,
  performance: BarChart3,
  oem: Cpu,
  actions: Sparkles,
  settings: Settings,
}

const INVESTIGATION_COLORS = [
  "border-l-accent",
  "border-l-warning",
  "border-l-severity-info",
  "border-l-danger",
]

function investigationColor(id?: string) {
  if (!id) return ""
  let h = 0
  for (let i = 0; i < id.length; i++) h = (h + id.charCodeAt(i) * (i + 1)) % INVESTIGATION_COLORS.length
  return INVESTIGATION_COLORS[h]
}

export function WorkspaceTabBar() {
  const tabs = useWorkspaceStore((s) => s.tabs)
  const activeTabId = useWorkspaceStore((s) => s.activeTabId)
  const activateTab = useWorkspaceStore((s) => s.activateTab)
  const closeTab = useWorkspaceStore((s) => s.closeTab)
  const closeOthers = useWorkspaceStore((s) => s.closeOthers)
  const pinTab = useWorkspaceStore((s) => s.pinTab)
  const reorderTabs = useWorkspaceStore((s) => s.reorderTabs)
  const dragFrom = useRef<number | null>(null)

  return (
    <div className="flex h-9 shrink-0 items-stretch border-b border-border bg-surface-2/80">
      <div className="flex min-w-0 flex-1 items-stretch gap-0.5 overflow-x-auto px-1 scrollbar-none">
        {tabs.map((tab, index) => (
          <TabChip
            key={tab.id}
            tab={tab}
            active={tab.id === activeTabId}
            onActivate={() => activateTab(tab.id)}
            onClose={() => closeTab(tab.id)}
            onCloseOthers={() => closeOthers(tab.id)}
            onPin={() => pinTab(tab.id)}
            onDragStart={() => {
              dragFrom.current = index
            }}
            onDrop={() => {
              if (dragFrom.current != null && dragFrom.current !== index) {
                reorderTabs(dragFrom.current, index)
              }
              dragFrom.current = null
            }}
          />
        ))}
      </div>

      {tabs.length > 4 && (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              type="button"
              className="flex w-8 shrink-0 items-center justify-center border-l border-border text-muted hover:bg-surface-3 hover:text-foreground"
              title="Tous les espaces"
              aria-label="Tous les espaces de travail"
            >
              <ChevronDown className="size-3.5" />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="min-w-48">
            {tabs.map((tab) => {
              const Icon = TYPE_ICON[tab.type]
              return (
                <DropdownMenuItem
                  key={tab.id}
                  onClick={() => activateTab(tab.id)}
                  className={cn(tab.id === activeTabId && "bg-accent-soft text-accent")}
                >
                  <Icon className="size-3.5" />
                  <span className="truncate">{tab.title}</span>
                </DropdownMenuItem>
              )
            })}
          </DropdownMenuContent>
        </DropdownMenu>
      )}
    </div>
  )
}

function TabChip({
  tab,
  active,
  onActivate,
  onClose,
  onCloseOthers,
  onPin,
  onDragStart,
  onDrop,
}: {
  tab: WorkspaceTab
  active: boolean
  onActivate: () => void
  onClose: () => void
  onCloseOthers: () => void
  onPin: () => void
  onDragStart: () => void
  onDrop: () => void
}) {
  const Icon = TYPE_ICON[tab.type]
  const inv = investigationColor(tab.investigationId)
  const [menuOpen, setMenuOpen] = useState(false)

  return (
    <DropdownMenu open={menuOpen} onOpenChange={setMenuOpen}>
      <div
        role="tab"
        aria-selected={active}
        draggable
        onDragStart={onDragStart}
        onDragOver={(e) => e.preventDefault()}
        onDrop={onDrop}
        onClick={onActivate}
        onContextMenu={(e) => {
          e.preventDefault()
          setMenuOpen(true)
        }}
        onAuxClick={(e) => {
          if (e.button === 1) {
            e.preventDefault()
            if (!tab.isPinned) onClose()
          }
        }}
        className={cn(
          "group relative flex max-w-[200px] cursor-pointer items-center gap-1.5 border-b-2 px-2.5 text-[11px] transition-colors",
          tab.isPinned ? "min-w-0 max-w-[140px]" : "min-w-[120px]",
          inv && `border-l-2 ${inv}`,
          active
            ? "border-b-accent bg-surface text-foreground"
            : "border-b-transparent text-muted hover:bg-surface/80 hover:text-foreground"
        )}
        title={tab.title}
      >
        <Icon className="size-3 shrink-0 opacity-70" />
        {tab.isPinned ? <Pin className="size-2.5 shrink-0 text-muted-2" /> : null}
        <span className="min-w-0 flex-1 truncate font-medium">{tab.title}</span>
        {tab.isDirty ? (
          <span className="size-1.5 shrink-0 rounded-full bg-warning" title="Modifié" />
        ) : null}
        {!tab.isPinned && (
          <button
            type="button"
            className="flex size-4 shrink-0 items-center justify-center rounded-sm text-muted-2 opacity-0 hover:bg-surface-3 hover:text-foreground group-hover:opacity-100"
            onClick={(e) => {
              e.stopPropagation()
              onClose()
            }}
            aria-label={`Fermer ${tab.title}`}
          >
            <X className="size-3" />
          </button>
        )}
        {/* Anchor for Radix positioning — invisible, no separate trigger UX */}
        <DropdownMenuTrigger asChild>
          <span className="pointer-events-none absolute inset-0" aria-hidden />
        </DropdownMenuTrigger>
      </div>
      <DropdownMenuContent align="start" className="min-w-[9.5rem]">
        <DropdownMenuItem disabled={tab.isPinned} onClick={onClose}>
          Fermer
        </DropdownMenuItem>
        <DropdownMenuItem onClick={onCloseOthers}>Fermer les autres</DropdownMenuItem>
        <DropdownMenuItem onClick={onPin}>
          {tab.isPinned ? "Désépingler" : "Épingler"}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
