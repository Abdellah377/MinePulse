import { useEffect, useRef } from "react"
import { useLocation, useNavigate } from "react-router-dom"

import { useWorkspaceStore, useActiveWorkspace } from "@/lib/store/useWorkspaceStore"
import type { WorkspaceModule } from "@/lib/workspace/types"

const PATH_MODULE: { match: string; module: WorkspaceModule }[] = [
  { match: "/performance", module: "performance" },
  { match: "/oem", module: "oem" },
  { match: "/actions", module: "actions" },
  { match: "/alertes", module: "alertes" },
  { match: "/parametres", module: "parametres" },
]

const LEGACY_REDIRECT: { match: string; to: string }[] = [
  { match: "/supervision", to: "/alertes" },
  { match: "/evenements", to: "/alertes" },
  { match: "/optimisation", to: "/actions" },
]

function moduleFromPath(pathname: string): WorkspaceModule | null {
  if (pathname === "/") return "alertes"
  const hit = PATH_MODULE.find((p) => pathname.startsWith(p.match))
  return hit?.module ?? null
}

/** When user hits a module URL directly, open/focus that module's home workspace. */
export function ModuleRouteSync() {
  const location = useLocation()
  const navigate = useNavigate()
  const openModuleHome = useWorkspaceStore((s) => s.openModuleHome)
  const active = useActiveWorkspace()
  const lastSynced = useRef<string | null>(null)

  useEffect(() => {
    if (location.pathname.startsWith("/equipement/")) return
    if (location.pathname.startsWith("/dev/simulation")) return

    const legacy = LEGACY_REDIRECT.find((p) => location.pathname.startsWith(p.match))
    if (legacy) {
      navigate(legacy.to, { replace: true })
      return
    }

    const mod = moduleFromPath(location.pathname)
    if (!mod) return
    if (lastSynced.current === location.pathname) return
    lastSynced.current = location.pathname
    if (active?.module === mod) return
    openModuleHome(mod)
  }, [location.pathname, openModuleHome, active?.module, navigate])

  return null
}
