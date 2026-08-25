import { useEffect } from "react"

import { oemApi } from "@/lib/api/oem"
import type { OemCol } from "@/lib/oem/types"
import { OemGrid } from "@/components/oem/OemDataTable"
import { OemEmptyState } from "@/components/oem/OemEmptyState"
import { codesQuery, rangeParams, useOemLoad, type OemViewProps } from "@/components/oem/oemViewUtils"
import { useOpsStore } from "@/lib/store/useOpsStore"

const COLS: OemCol[] = [
  { id: "code", header: "Engin" },
  { id: "parameter", header: "Paramètre" },
  { id: "unit", header: "Unité" },
  { id: "avg", header: "Moyenne", align: "right" },
  { id: "min", header: "Minimum", align: "right" },
  { id: "max", header: "Maximum", align: "right" },
  { id: "aboveThreshold", header: "Occurrences alarme haute", align: "right", tone: "alarm-red" },
  { id: "belowThreshold", header: "Occurrences alarme basse", align: "right", tone: "alarm-red" },
  { id: "reportIntervalSec", header: "Fréquence de remontée, sec.", align: "right" },
  { id: "lastValue", header: "Dernière valeur", align: "right" },
]

export function IndicatorsTable({ filters, refreshKey, onExport }: OemViewProps) {
  const shifts = useOpsStore((s) => s.shifts)
  const r = rangeParams(filters, shifts)
  const { data, error, loading } = useOemLoad(
    () =>
      oemApi.maintenance({
        codes: codesQuery(filters.equipmentCodes),
        params: codesQuery(filters.parameterKeys),
        from: r.from,
        to: r.to,
      }),
    [refreshKey, filters.equipmentCodes.join(","), filters.parameterKeys.join(","), r.from, r.to]
  )
  const rows = data?.rows ?? []

  useEffect(() => {
    onExport?.({
      rows,
      columns: COLS,
      filename: `MinePulse_OEM_Indicateurs_${new Date().toISOString().slice(0, 10)}.xlsx`,
    })
  }, [rows, onExport])

  if (loading) return <OemEmptyState message="Chargement…" />
  if (error) return <OemEmptyState message={error} />
  if (!filters.equipmentCodes.length) return <OemEmptyState message="Sélectionnez un engin, puis Actualiser." />
  return <OemGrid columns={COLS} rows={rows} />
}
