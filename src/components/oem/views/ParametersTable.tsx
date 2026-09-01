import { useEffect } from "react"

import { useOemApi, EMPTY_OEM_ROWS } from "@/components/oem/oemViewUtils"
import type { OemCol } from "@/lib/oem/types"
import { OemGrid } from "@/components/oem/OemDataTable"
import { OemEmptyState } from "@/components/oem/OemEmptyState"
import { codesQuery, useAnalysisRangeParams, useOemLoad, type OemViewProps } from "@/components/oem/oemViewUtils"

const COLS: OemCol[] = [
  { id: "thresholdSource", header: "Source seuils (non constructeur)" },
  { id: "code", header: "Engin" },
  { id: "parameter", header: "Paramètres Diagnostic" },
  { id: "parameterKey", header: "Code" },
  { id: "ts", header: "Heure" },
  { id: "min", header: "Valeur minimale", align: "right" },
  { id: "avg", header: "Valeur moyenne", align: "right" },
  { id: "max", header: "Valeur maximale", align: "right" },
  { id: "unit", header: "Unité de mesure" },
  { id: "sensorWorking", header: "Fonctionnement du capteur" },
]

export function ParametersTable({ filters, refreshKey, onExport }: OemViewProps) {
  const oemApi = useOemApi()
  const r = useAnalysisRangeParams()
  const { data, error, loading } = useOemLoad(
    () =>
      oemApi.diagnostic({
        codes: codesQuery(filters.equipmentCodes),
        params: codesQuery(filters.parameterKeys),
        from: r.from,
        to: r.to,
      }),
    [refreshKey, filters.equipmentCodes.join(","), filters.parameterKeys.join(","), r.from, r.to]
  )
  const rows = data?.rows ?? EMPTY_OEM_ROWS

  useEffect(() => {
    onExport?.({
      rows,
      columns: COLS,
      filename: `MinePulse_OEM_Diagnostic_${new Date().toISOString().slice(0, 10)}.xlsx`,
    })
  }, [rows, onExport])

  if (loading) return <OemEmptyState message="Chargement…" />
  if (error) return <OemEmptyState message={error} />
  if (!filters.equipmentCodes.length) return <OemEmptyState message="Sélectionnez un engin, puis Actualiser." />
  if (rows.length === 0) {
    return <OemEmptyState message="Les données de diagnostic ne sont pas disponibles sur cette période." />
  }
  return <OemGrid columns={COLS} rows={rows} />
}
