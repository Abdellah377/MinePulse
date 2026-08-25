import { useEffect } from "react"

import { oemApi } from "@/lib/api/oem"
import type { OemCol } from "@/lib/oem/types"
import { OemGrid } from "@/components/oem/OemDataTable"
import { OemEmptyState } from "@/components/oem/OemEmptyState"
import { codesQuery, rangeParams, useOemLoad, type OemViewProps } from "@/components/oem/oemViewUtils"
import { useOpsStore } from "@/lib/store/useOpsStore"

const COLS: OemCol[] = [
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
  const shifts = useOpsStore((s) => s.shifts)
  const r = rangeParams(filters, shifts)
  const { data, error, loading } = useOemLoad(
    () =>
      oemApi.anomalies({
        codes: codesQuery(filters.equipmentCodes),
        from: r.from,
        to: r.to,
      }),
    [refreshKey, filters.equipmentCodes.join(","), r.from, r.to]
  )
  const rows = data?.rows ?? []

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
