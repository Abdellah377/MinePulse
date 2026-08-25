import { lazy, Suspense } from "react"
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom"
import { Loader2 } from "lucide-react"

import { AppErrorBoundary } from "@/components/shared/AppErrorBoundary"

const AppShell = lazy(() =>
  import("@/components/layout/AppShell").then((m) => ({ default: m.AppShell }))
)
const EquipmentPage = lazy(() => import("@/pages/EquipmentPage"))
const SimulationCentre = lazy(() => import("@/pages/dev/SimulationCentre"))

function RouteFallback() {
  return (
    <div className="flex h-screen w-screen flex-col items-center justify-center gap-3 bg-background">
      <Loader2 className="size-5 animate-spin text-accent" />
      <p className="text-sm text-muted">Chargement MinePulse…</p>
    </div>
  )
}

function App() {
  return (
    <AppErrorBoundary>
      <BrowserRouter>
        <Suspense fallback={<RouteFallback />}>
          <Routes>
            <Route element={<AppShell />}>
              <Route path="/" element={null} />
              <Route path="/alertes" element={null} />
              <Route path="/actions" element={null} />
              <Route path="/performance" element={null} />
              <Route path="/oem" element={null} />
              <Route path="/parametres" element={null} />
              <Route path="/supervision/*" element={<Navigate to="/alertes" replace />} />
              <Route path="/evenements" element={<Navigate to="/alertes" replace />} />
              <Route path="/optimisation" element={<Navigate to="/actions" replace />} />
              <Route path="/equipement/:id" element={<EquipmentPage />} />
              <Route path="/dev/simulation" element={<SimulationCentre />} />
              <Route path="*" element={<Navigate to="/alertes" replace />} />
            </Route>
          </Routes>
        </Suspense>
      </BrowserRouter>
    </AppErrorBoundary>
  )
}

export default App
