import { Suspense, lazy, type ComponentType } from "react"
import { Loader2 } from "lucide-react"

import { useWorkspaceStore, useActiveWorkspace } from "@/lib/store/useWorkspaceStore"
import type { WorkspaceTab } from "@/lib/workspace/types"
import { PosteBar } from "@/components/layout/PosteBar"

const AlertesIA = lazy(() => import("@/pages/AlertesIA"))
const Carte = lazy(() => import("@/pages/supervision/Carte"))
const Film = lazy(() => import("@/pages/supervision/Film"))
const Performance = lazy(() => import("@/pages/Performance"))
const OemPage = lazy(() => import("@/pages/oem/OemPage"))
const ActionsIA = lazy(() => import("@/pages/ActionsIA"))
const Parametres = lazy(() => import("@/pages/Parametres"))

function Fallback() {
  return (
    <div className="flex h-full items-center justify-center">
      <Loader2 className="size-4 animate-spin text-muted-2" />
    </div>
  )
}

export type WorkspacePanelProps = {
  tab: WorkspaceTab
}

const PANEL: Record<WorkspaceTab["type"], ComponentType<WorkspacePanelProps> | ComponentType> = {
  alerts: AlertesIA,
  map: Carte,
  timeline: Film,
  performance: Performance,
  oem: OemPage,
  actions: ActionsIA,
  settings: Parametres,
}

const KEEP_ALIVE = new Set(["map", "timeline"])

/** Renders open workspaces. Heavy map/film stay mounted+hidden while open. */
export function WorkspaceHost() {
  const tabs = useWorkspaceStore((s) => s.tabs)
  const active = useActiveWorkspace()
  const showPoste = active?.module === "alertes"

  const keepAliveTabs = tabs.filter((t) => KEEP_ALIVE.has(t.type))
  const activeNeedsKeep = Boolean(active && KEEP_ALIVE.has(active.type))

  return (
    <div className="flex h-full min-h-0 w-full flex-col overflow-hidden">
      {showPoste ? <PosteBar /> : null}
      <div className="relative min-h-0 w-full flex-1 overflow-hidden">
        <Suspense fallback={<Fallback />}>
          {keepAliveTabs.map((tab) => {
            const Comp = PANEL[tab.type]
            if (!Comp) return null
            const isActive = tab.id === active?.id
            return (
              <div key={tab.id} className={panelClass(isActive)} aria-hidden={!isActive}>
                <Comp tab={tab} />
              </div>
            )
          })}

          {active && !activeNeedsKeep
            ? (() => {
                const Comp = PANEL[active.type]
                if (!Comp) {
                  return (
                    <div className="flex h-full items-center justify-center text-xs text-muted">
                      Espace inconnu ({active.type}).
                    </div>
                  )
                }
                return (
                  <div key={active.id} className="absolute inset-0 overflow-hidden">
                    <Comp tab={active} />
                  </div>
                )
              })()
            : null}

          {!active ? (
            <div className="flex h-full items-center justify-center text-xs text-muted">
              Aucun espace de travail ouvert.
            </div>
          ) : null}
        </Suspense>
      </div>
    </div>
  )
}

function panelClass(active: boolean) {
  return active
    ? "absolute inset-0 overflow-hidden"
    : "pointer-events-none invisible absolute inset-0 overflow-hidden"
}
