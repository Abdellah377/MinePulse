import { useNavigate, useLocation } from "react-router-dom"
import { Search, Bell, ChevronDown } from "lucide-react"

import { cn } from "@/lib/utils"
import { timeAgo } from "@/lib/format"
import { useOpsStore } from "@/lib/store/useOpsStore"
import { useUiStore } from "@/lib/store/useUiStore"
import { useWorkspaceStore, useActiveWorkspace } from "@/lib/store/useWorkspaceStore"
import type { WorkspaceModule, WorkspaceType } from "@/lib/workspace/types"
import { SEVERITY_CONFIG } from "@/lib/status"
import { OcpLogo } from "@/components/brand/OcpLogo"
import { DataFreshnessIndicator } from "@/components/shared/DataFreshnessIndicator"
import { OemCatalogMenu } from "@/components/oem/OemCatalogMenu"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"

type NavItem =
  | {
      kind: "module"
      module: WorkspaceModule
      /** When set, only active for this workspace type (not sibling terrain tabs). */
      activeType?: WorkspaceType
      label: string
      short: string
      path: string
    }
  | {
      kind: "workspace"
      type: WorkspaceType
      label: string
      short: string
    }

const NAV: NavItem[] = [
  {
    kind: "module",
    module: "alertes",
    activeType: "alerts",
    label: "ALERTES IA",
    short: "ALERTES",
    path: "/alertes",
  },
  { kind: "workspace", type: "map", label: "CARTE", short: "CARTE" },
  { kind: "workspace", type: "timeline", label: "FILM", short: "FILM" },
  { kind: "module", module: "actions", label: "ACTIONS IA", short: "ACTIONS", path: "/actions" },
  {
    kind: "module",
    module: "performance",
    label: "PERFORMANCE",
    short: "PERF.",
    path: "/performance",
  },
  { kind: "module", module: "oem", label: "OEM", short: "OEM", path: "/oem" },
  { kind: "module", module: "parametres", label: "PARAMÈTRES", short: "PARAM.", path: "/parametres" },
]

export function BrandHeader() {
  const navigate = useNavigate()
  const location = useLocation()

  const sites = useOpsStore((s) => s.sites)
  const selectedSiteId = useOpsStore((s) => s.selectedSiteId)
  const setSelectedSite = useOpsStore((s) => s.setSelectedSite)
  const alerts = useOpsStore((s) => s.alerts)
  const setCommandOpen = useUiStore((s) => s.setCommandOpen)
  const openModuleHome = useWorkspaceStore((s) => s.openModuleHome)
  const openWorkspace = useWorkspaceStore((s) => s.openWorkspace)
  const active = useActiveWorkspace()

  const unresolved = alerts.filter((a) => a.status !== "resolved").length
  const recentAlerts = [...alerts]
    .filter((a) => a.status !== "resolved")
    .sort((a, b) => b.createdAt - a.createdAt)
    .slice(0, 5)

  function goModule(module: WorkspaceModule, path: string) {
    openModuleHome(module)
    navigate(path)
  }

  function goTerrain(type: WorkspaceType) {
    openWorkspace({ type })
    // Stay under /alertes shell so ModuleRouteSync does not steal the tab
    if (!location.pathname.startsWith("/alertes") && location.pathname !== "/") {
      navigate("/alertes")
    }
  }

  function isNavActive(item: NavItem): boolean {
    if (!active) return false
    if (item.kind === "workspace") return active.type === item.type
    if (item.activeType) return active.type === item.activeType
    return active.module === item.module
  }

  return (
    <header className="flex h-11 shrink-0 items-center gap-2 overflow-hidden bg-brand-header px-2 text-white sm:gap-3 sm:px-3">
      <div className="flex min-w-0 flex-1 items-center gap-2 overflow-hidden">
        <button
          type="button"
          onClick={() => goModule("alertes", "/alertes")}
          className="flex shrink-0 items-center gap-1.5"
        >
          <OcpLogo variant="header" className="h-8 w-auto max-w-[48px]" title="OCP Group" />
          <span className="hidden text-[12px] font-semibold tracking-wide xl:inline">MinePulse</span>
        </button>

        <nav className="flex h-11 min-w-0 items-stretch overflow-x-auto scrollbar-none">
          {NAV.map((item) => {
            const isActive = isNavActive(item)
            const key = item.kind === "module" ? item.path : item.type
            if (item.kind === "module" && item.module === "oem") {
              return <OemCatalogMenu key={key} active={isActive} />
            }
            return (
              <button
                key={key}
                type="button"
                title={item.label}
                onClick={() => {
                  if (item.kind === "module") goModule(item.module, item.path)
                  else goTerrain(item.type)
                }}
                className={cn(
                  "flex shrink-0 items-center border-b-2 px-2 text-[10px] font-semibold tracking-wider transition-colors lg:px-2.5 lg:text-[11px]",
                  isActive
                    ? "border-white bg-black/10 text-white"
                    : "border-transparent text-white/80 hover:bg-black/10 hover:text-white"
                )}
              >
                <span className="xl:hidden">{item.short}</span>
                <span className="hidden xl:inline">{item.label}</span>
                {item.kind === "module" && item.module === "alertes" && unresolved > 0 ? (
                  <span className="ml-1 min-w-4 rounded-sm bg-danger/90 px-1 text-center text-[10px] font-bold leading-4 text-white">
                    {unresolved}
                  </span>
                ) : null}
              </button>
            )
          })}
        </nav>
      </div>

      <div className="flex shrink-0 items-center gap-1.5 sm:gap-2">
        {sites.length > 0 ? (
          <Select value={selectedSiteId} onValueChange={setSelectedSite}>
            <SelectTrigger className="h-7 w-[9.5rem] max-w-[9.5rem] truncate rounded-md border-white/20 bg-black/15 text-[11px] text-white hover:bg-black/25 sm:w-[12rem] sm:max-w-[12rem] lg:w-[14rem] lg:max-w-[14rem] [&>svg]:text-white/70">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {sites.map((site) => (
                <SelectItem key={site.id} value={site.id}>
                  {site.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        ) : (
          <span className="h-7 rounded-md border border-white/20 bg-black/15 px-2 text-[11px] leading-7 text-white/70">
            Site…
          </span>
        )}

        <button
          type="button"
          onClick={() => setCommandOpen(true)}
          className="flex h-7 w-7 items-center justify-center rounded-md border border-white/20 bg-black/15 text-white/80 transition-colors hover:bg-black/25 hover:text-white lg:w-40 lg:justify-start lg:gap-1.5 lg:px-2.5"
          aria-label="Rechercher"
          title="Rechercher (Ctrl+K)"
        >
          <Search className="size-3.5 shrink-0" />
          <span className="hidden flex-1 truncate text-left text-[11px] text-white/70 lg:inline">
            Rechercher…
          </span>
          <kbd className="hidden rounded-md border border-white/20 px-1 font-mono text-[9px] text-white/50 lg:inline">
            ⌘K
          </kbd>
        </button>

        <DataFreshnessIndicator muted />

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              type="button"
              className="relative flex size-7 shrink-0 items-center justify-center rounded-md bg-white/15 text-white hover:bg-white/25"
              aria-label="Alertes"
            >
              <Bell className="size-3.5" />
              {recentAlerts.length > 0 && (
                <span className="absolute right-1.5 top-1.5 size-2 rounded-full bg-danger ring-2 ring-brand-header" />
              )}
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-80">
            <DropdownMenuLabel>Alertes récentes</DropdownMenuLabel>
            <DropdownMenuSeparator />
            {recentAlerts.length === 0 && (
              <div className="px-2 py-4 text-center text-xs text-muted">Aucune alerte active</div>
            )}
            {recentAlerts.map((alert) => {
              const cfg = SEVERITY_CONFIG[alert.severity]
              return (
                <DropdownMenuItem
                  key={alert.id}
                  onClick={() => {
                    openWorkspace({
                      type: "alerts",
                      context: { alertId: alert.id },
                      title: alert.title,
                    })
                    navigate("/alertes")
                  }}
                  className="flex-col items-start gap-0.5 py-2"
                >
                  <div className="flex w-full items-center gap-1.5">
                    <span className={cn("size-1.5 rounded-full", cfg.dot)} />
                    <span className="font-medium">{alert.title}</span>
                    <span className="ml-auto text-[10px] text-muted-2">{timeAgo(alert.createdAt)}</span>
                  </div>
                  <p className="line-clamp-1 pl-3 text-[11px] text-muted">{alert.description}</p>
                </DropdownMenuItem>
              )
            })}
            <DropdownMenuSeparator />
            <DropdownMenuItem
              onClick={() => {
                openModuleHome("alertes")
                navigate("/alertes")
              }}
              className="justify-center text-accent"
            >
              Voir toutes les alertes
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              type="button"
              className="flex h-7 shrink-0 items-center gap-1.5 rounded-md px-1 text-[11px] font-medium text-white hover:bg-white/15 sm:pr-2"
            >
              <span className="flex size-6 items-center justify-center rounded-lg bg-white text-[10px] font-bold text-brand-header">
                CP
              </span>
              <span className="hidden sm:inline">Chef de poste</span>
              <ChevronDown className="hidden size-3 opacity-70 sm:inline" />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuLabel>Compte poste</DropdownMenuLabel>
            <DropdownMenuLabel className="-mt-2 normal-case tracking-normal text-muted">
              Session active
            </DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuItem onClick={() => goModule("parametres", "/parametres")}>
              Paramètres
            </DropdownMenuItem>
            <DropdownMenuItem>Déconnexion</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>
  )
}
