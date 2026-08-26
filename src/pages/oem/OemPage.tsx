import { useCallback, useEffect, useMemo, useState } from "react"
import { useNavigate } from "react-router-dom"

import { useApiMode } from "@/lib/api/client"
import {
  DEFAULT_OEM_DRAFT,
  defaultDiagnosticTab,
  defaultMaintenanceTab,
  oemFamilyForView,
  resolveOemView,
  type OemDraft,
} from "@/lib/oem/types"
import { oemOpenContext } from "@/lib/oem/openOem"
import { useOpsStore, useSiteScopedEquipment } from "@/lib/store/useOpsStore"
import { useWorkspaceStore } from "@/lib/store/useWorkspaceStore"
import type { OemDiagnosticTab, OemMaintenanceTab } from "@/lib/workspace/types"
import { oemViewTitle } from "@/lib/workspace/titles"
import type { WorkspacePanelProps } from "@/components/workspace/WorkspaceHost"
import { OemFilterPanel } from "@/components/oem/OemFilterPanel"
import { OemEmptyState } from "@/components/oem/OemEmptyState"
import { OemReportContextBar, OemReportLayout } from "@/components/oem/OemReportLayout"
import { ConnectivityReport } from "@/components/oem/views/ConnectivityReport"
import { DiagnosticWorkspace } from "@/components/oem/views/DiagnosticWorkspace"
import { MaintenanceWorkspace } from "@/components/oem/views/MaintenanceWorkspace"
import { TyreCharts } from "@/components/oem/views/TyreCharts"
import { SpeedFuelCharts } from "@/components/oem/views/SpeedFuelCharts"
import { PayloadSpeedFuelCharts } from "@/components/oem/views/PayloadSpeedFuelCharts"
import { MultiSignalExplorer } from "@/components/oem/views/MultiSignalExplorer"
import { oemContext, type OemExportPayload } from "@/components/oem/oemViewUtils"

function asDraft(raw: Record<string, unknown>, fallbackCode?: string): OemDraft {
  const codes = Array.isArray(raw.equipmentCodes)
    ? (raw.equipmentCodes as string[])
    : typeof raw.equipmentCode === "string" && raw.equipmentCode
      ? [String(raw.equipmentCode)]
      : fallbackCode
        ? [fallbackCode]
        : []
  return {
    ...DEFAULT_OEM_DRAFT,
    ...raw,
    equipmentCodes: codes,
    equipmentType: String(raw.equipmentType ?? "all"),
    periodMode: (raw.periodMode as OemDraft["periodMode"]) ?? "shift",
    parameterKeys: Array.isArray(raw.parameterKeys) ? (raw.parameterKeys as string[]) : [],
    tyrePositions: Array.isArray(raw.tyrePositions)
      ? (raw.tyrePositions as string[])
      : DEFAULT_OEM_DRAFT.tyrePositions,
    minDelaySec: Number(raw.minDelaySec ?? 30),
  }
}

export default function OemPage({ tab }: Partial<WorkspacePanelProps> = {}) {
  const navigate = useNavigate()
  const openWorkspace = useWorkspaceStore((s) => s.openWorkspace)
  const setTabTitle = useWorkspaceStore((s) => s.setTabTitle)
  const patchTabContext = useWorkspaceStore((s) => s.patchTabContext)
  const setTabState = useWorkspaceStore((s) => s.setTabState)
  const getTabState = useWorkspaceStore((s) => s.getTabState)
  const equipment = useSiteScopedEquipment()
  const sites = useOpsStore((s) => s.sites)
  const selectedSiteId = useOpsStore((s) => s.selectedSiteId)
  const shifts = useOpsStore((s) => s.shifts)
  const selectedShiftId = useOpsStore((s) => s.selectedShiftId)

  const view = resolveOemView(tab?.context.oemView as string | undefined)
  const family = oemFamilyForView(view)
  const saved = tab?.id ? getTabState(tab.id) : {}
  const initialCode = String(tab?.context.equipmentCode ?? "")
  const [draft, setDraft] = useState<OemDraft>(() => asDraft(saved, initialCode))
  const [applied, setApplied] = useState<OemDraft>(() => asDraft(saved, initialCode))
  const [refreshKey, setRefreshKey] = useState(0)
  const [exportState, setExportState] = useState<{ key: string; payload: OemExportPayload | null } | null>(null)
  const [diagnosticTab, setDiagnosticTab] = useState<OemDiagnosticTab>(
    () => (saved.diagnosticTab as OemDiagnosticTab) ?? defaultDiagnosticTab(tab?.context.oemView as string)
  )
  const [maintenanceTab, setMaintenanceTab] = useState<OemMaintenanceTab>(
    () => (saved.maintenanceTab as OemMaintenanceTab) ?? defaultMaintenanceTab(tab?.context.oemView as string)
  )

  useEffect(() => {
    const stored = tab?.id ? getTabState(tab.id) : {}
    const next = asDraft(stored, String(tab?.context.equipmentCode ?? ""))
    setDraft(next)
    setApplied(next)
    setExportState(null)
    setDiagnosticTab((stored.diagnosticTab as OemDiagnosticTab) ?? defaultDiagnosticTab(tab?.context.oemView as string))
    setMaintenanceTab(
      (stored.maintenanceTab as OemMaintenanceTab) ?? defaultMaintenanceTab(tab?.context.oemView as string)
    )
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab?.id])

  useEffect(() => {
    if (draft.equipmentCodes.length || !equipment.length) return
    const first =
      equipment.find((e) => e.code === initialCode) ??
      equipment.find((e) => e.type === "haul_truck") ??
      equipment[0]
    if (first) {
      const next = { ...draft, equipmentCodes: [first.code] }
      setDraft(next)
      setApplied(next)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [equipment.length, tab?.id])

  useEffect(() => {
    if (!tab?.id) return
    const focus = applied.equipmentCodes[0]
    const title =
      view === "connectivite" ? oemViewTitle(view) : focus ? `${oemViewTitle(view)} — ${focus}` : oemViewTitle(view)
    setTabTitle(tab.id, title)
    if (view === "connectivite") {
      patchTabContext(tab.id, { oemFamily: family, oemView: view, equipmentCode: undefined })
    } else {
      patchTabContext(tab.id, { oemFamily: family, oemView: view, equipmentCode: focus })
    }
    setTabState(tab.id, { ...draft, family, view, diagnosticTab, maintenanceTab })
  }, [
    tab?.id,
    family,
    view,
    draft,
    applied,
    diagnosticTab,
    maintenanceTab,
    setTabTitle,
    patchTabContext,
    setTabState,
  ])

  const siteName = sites.find((s) => s.id === selectedSiteId)?.name ?? selectedSiteId
  const shiftLabel = shifts.find((s) => s.id === selectedShiftId)?.name ?? selectedShiftId
  const internalTab = view === "diagnostic" ? diagnosticTab : view === "maintenance" ? maintenanceTab : undefined
  const reportKey = JSON.stringify([selectedSiteId, selectedShiftId, view, internalTab, applied])
  const exportPayload = exportState?.key === reportKey ? exportState.payload : null

  const onExport = useCallback((payload: OemExportPayload | null) => {
    setExportState({ key: reportKey, payload })
  }, [reportKey])

  const viewProps = useMemo(
    () => ({
      filters: applied,
      refreshKey,
      siteName,
      shiftLabel,
      onExport,
      onOpenEquipment: (code: string) => {
        openWorkspace({ type: "oem", context: oemOpenContext("diagnostic", code) })
        navigate("/oem")
      },
    }),
    [applied, refreshKey, siteName, shiftLabel, onExport, openWorkspace, navigate]
  )

  if (!useApiMode) {
    return (
      <div className="flex h-full items-center justify-center px-2 py-2">
        <OemEmptyState message="Le module OEM nécessite le mode API (VITE_USE_API=true)." />
      </div>
    )
  }

  return (
    <OemReportLayout
      key={reportKey}
      panel={
        <OemFilterPanel
          view={view}
          internalTab={internalTab}
          draft={draft}
          onChange={setDraft}
          onApply={() => {
            setApplied(draft)
            setRefreshKey((k) => k + 1)
          }}
          exportRows={exportPayload?.rows}
          exportCols={exportPayload?.columns}
          exportContext={oemContext(applied, siteName, shiftLabel)}
          exportName={exportPayload?.filename}
        />
      }
      context={<OemReportContextBar view={view} siteName={siteName} filters={applied} />}
    >
      {view === "connectivite" ? <ConnectivityReport {...viewProps} /> : null}
      {view === "diagnostic" ? (
        <DiagnosticWorkspace {...viewProps} tab={diagnosticTab} onTabChange={setDiagnosticTab} />
      ) : null}
      {view === "maintenance" ? (
        <MaintenanceWorkspace {...viewProps} tab={maintenanceTab} onTabChange={setMaintenanceTab} />
      ) : null}
      {view === "pneus" ? <TyreCharts {...viewProps} /> : null}
      {view === "vitesse-gasoil" ? <SpeedFuelCharts {...viewProps} /> : null}
      {view === "poids" ? <PayloadSpeedFuelCharts {...viewProps} /> : null}
      {view === "multi" ? <MultiSignalExplorer {...viewProps} /> : null}
    </OemReportLayout>
  )
}
