import { useEffect } from "react"

import { useOemApi, EMPTY_OEM_ROWS } from "@/components/oem/oemViewUtils"
import type { OemCol } from "@/lib/oem/types"
import { OemGrid } from "@/components/oem/OemDataTable"
import { OemEmptyState } from "@/components/oem/OemEmptyState"
import { codesQuery, useAnalysisRangeParams, useOemLoad, type OemViewProps } from "@/components/oem/oemViewUtils"

const COLS: OemCol[] = [
  { id: "catalogSource", header: "Source catalogue" },
  { id: "thresholdSource", header: "Source plage" },
  { id: "ts", header: "Heure" },
  { id: "code", header: "Engin" },
  { id: "parameter", header: "Paramètre" },
  { id: "value", header: "Valeur", align: "right" },
  { id: "expectedRange", header: "Plage attendue" },
  { id: "anomalyType", header: "Type anomalie" },
  { id: "severity", header: "Sévérité" },
  { id: "durationSec", header: "Durée", align: "right" },
  { id: "status", header: "Statut" },
]

export function AnomaliesTable({ filters, refreshKey, onExport }: OemViewProps) {
  const oemApi = useOemApi()
  const r = useAnalysisRangeParams()
  const { data, error, loading } = useOemLoad(
    () =>
      oemApi.anomalies({
        codes: codesQuery(filters.equipmentCodes),
        from: r.from,
        to: r.to,
      }),
    [refreshKey, filters.equipmentCodes.join(","), r.from, r.to]
  )
  const rows = data?.rows ?? EMPTY_OEM_ROWS

  useEffect(() => {
    onExport?.({
      rows,
      columns: COLS,
      filename: `MinePulse_OEM_Anomalies_${new Date().toISOString().slice(0, 10)}.xlsx`,
    })
  }, [rows, onExport])

  if (loading) return <OemEmptyState message="Chargement…" />
  if (error) return <OemEmptyState message={error} />
  return <OemGrid columns={COLS} rows={rows} />
}
