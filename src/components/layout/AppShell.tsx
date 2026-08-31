import { useEffect, useState } from "react"
import { Outlet, useLocation } from "react-router-dom"
import { Loader2 } from "lucide-react"

import { BrandHeader } from "@/components/layout/BrandHeader"
import { CommandPalette } from "@/components/layout/CommandPalette"
import { EquipmentDetailDrawer } from "@/components/equipment/EquipmentDetailDrawer"
import { AlertToasts } from "@/components/alerts/AlertToasts"
import { TooltipProvider } from "@/components/ui/tooltip"
import { Button } from "@/components/ui/button"
import { useApiMode } from "@/lib/api/client"
import { useLiveSimulation } from "@/lib/hooks/useLiveSimulation"
import { bootstrapOpsFromApi, useOpsStore } from "@/lib/store/useOpsStore"
import { WorkspaceTabBar } from "@/components/workspace/WorkspaceTabBar"
import { WorkspaceHost } from "@/components/workspace/WorkspaceHost"
import { ModuleRouteSync } from "@/components/workspace/ModuleRouteSync"
import { useWorkspaceKeyboard } from "@/components/workspace/useWorkspaceKeyboard"

const BOOTSTRAP_SAFETY_MS = 12_000

/** Routes that still use classical Outlet (equipment detail, sim centre). */
function useClassicOutlet() {
  const { pathname } = useLocation()
  return pathname.startsWith("/equipement/") || pathname.startsWith("/dev/simulation")
}

export function AppShell() {
  useLiveSimulation()
  useWorkspaceKeyboard()
  const classic = useClassicOutlet()
  const apiBootstrapped = useOpsStore((s) => s.apiBootstrapped)
  const [bootstrapTimedOut, setBootstrapTimedOut] = useState(false)
  const [retryKey, setRetryKey] = useState(0)

  useEffect(() => {
    if (!useApiMode) return

    let cancelled = false
    const safety = window.setTimeout(() => {
      if (cancelled || useOpsStore.getState().apiBootstrapped) return
      setBootstrapTimedOut(true)
      useOpsStore.setState({ apiBootstrapped: true })
    }, BOOTSTRAP_SAFETY_MS)

    void bootstrapOpsFromApi().finally(() => {
      if (!cancelled) window.clearTimeout(safety)
    })

    return () => {
      cancelled = true
      window.clearTimeout(safety)
    }
  }, [retryKey])

  if (useApiMode && !apiBootstrapped) {
    return (
      <div className="flex h-screen w-screen flex-col items-center justify-center gap-3 bg-background px-6 text-foreground">
        <Loader2 className="size-5 animate-spin text-accent" />
        <p className="text-sm text-muted">Connexion au backend opérationnel…</p>
        <p className="max-w-md text-center text-[11px] text-muted-2">
          API http://127.0.0.1:8000 · assurez-vous que{" "}
          <code className="rounded bg-surface-2 px-1">uvicorn app.main:app --port 8000</code> est accessible et la base PostgreSQL est configurée.
        </p>
      </div>
    )
  }

  return (
    <TooltipProvider>
      {bootstrapTimedOut ? (
        <div className="border-b border-amber-300/50 bg-amber-50 px-4 py-1.5 text-center text-[11px] text-amber-950">
          Bootstrap API lent ou indisponible — interface en mode dégradé.{" "}
          <Button
            type="button"
            variant="link"
            className="h-auto p-0 text-[11px] text-amber-900 underline"
            onClick={() => {
              setBootstrapTimedOut(false)
              useOpsStore.setState({ apiBootstrapped: false })
              setRetryKey((k) => k + 1)
            }}
          >
            Réessayer
          </Button>
        </div>
      ) : null}
      <ModuleRouteSync />
      <div className="flex h-screen w-screen flex-col overflow-hidden bg-background text-foreground">
        <BrandHeader />
        {!classic ? <WorkspaceTabBar /> : null}
        <main className="flex min-h-0 flex-1 flex-col overflow-hidden">
          {classic ? <Outlet /> : <WorkspaceHost />}
        </main>
      </div>
      <CommandPalette />
      <EquipmentDetailDrawer />
      <AlertToasts />
    </TooltipProvider>
  )
}
