import { IndicatorsTable } from "@/components/oem/views/IndicatorsTable"
import { AnomaliesTable } from "@/components/oem/views/AnomaliesTable"
import { OemInternalTabs } from "@/components/oem/OemInternalTabs"
import type { OemViewProps } from "@/components/oem/oemViewUtils"
import type { OemMaintenanceTab } from "@/lib/workspace/types"

const TABS: Array<{ id: OemMaintenanceTab; label: string }> = [
  { id: "indicateurs", label: "Indicateurs" },
  { id: "alarmes", label: "Alarmes / anomalies" },
]

export function MaintenanceWorkspace({
  tab,
  onTabChange,
  ...props
}: OemViewProps & { tab: OemMaintenanceTab; onTabChange: (tab: OemMaintenanceTab) => void }) {
  return (
    <OemInternalTabs tabs={TABS} value={tab} onChange={onTabChange}>
      {tab === "indicateurs" ? <IndicatorsTable {...props} /> : null}
      {tab === "alarmes" ? <AnomaliesTable {...props} /> : null}
    </OemInternalTabs>
  )
}
