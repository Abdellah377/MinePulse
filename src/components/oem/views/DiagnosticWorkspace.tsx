import { ParametersTable } from "@/components/oem/views/ParametersTable"
import { ErrorCodesTable } from "@/components/oem/views/ErrorCodesTable"
import { AnalyseCharts } from "@/components/oem/views/AnalyseCharts"
import { OemInternalTabs } from "@/components/oem/OemInternalTabs"
import type { OemViewProps } from "@/components/oem/oemViewUtils"
import type { OemDiagnosticTab } from "@/lib/workspace/types"

const TABS: Array<{ id: OemDiagnosticTab; label: string }> = [
  { id: "parametres", label: "Paramètres" },
  { id: "erreurs", label: "Codes erreur" },
  { id: "analyse", label: "Analyse" },
]

export function DiagnosticWorkspace({
  tab,
  onTabChange,
  ...props
}: OemViewProps & { tab: OemDiagnosticTab; onTabChange: (tab: OemDiagnosticTab) => void }) {
  return (
    <OemInternalTabs tabs={TABS} value={tab} onChange={onTabChange}>
      {tab === "parametres" ? <ParametersTable {...props} /> : null}
      {tab === "erreurs" ? <ErrorCodesTable {...props} /> : null}
      {tab === "analyse" ? <AnalyseCharts {...props} maxSignals={4} /> : null}
    </OemInternalTabs>
  )
}
