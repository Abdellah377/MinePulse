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
  { id: "errorCode", header: "Code erreur" },
  { id: "category", header: "Catégorie" },
  { id: "description", header: "Description" },
  { id: "severity", header: "Sévérité" },
  { id: "firstOccurrence", header: "Première occurrence" },
  { id: "lastOccurrence", header: "Dernière occurrence" },
  { id: "occurrences", header: "Nombre occurrences", align: "right" },
  { id: "status", header: "Statut" },
]

export function ErrorCodesTable({ filters, refreshKey, onExport }: OemViewProps) {
  const shifts = useOpsStore((s) => s.shifts)
  const r = rangeParams(filters, shifts)
  const { data, error, loading } = useOemLoad(
    () =>
      oemApi.errors({
        codes: codesQuery(filters.equipmentCodes),
        from: r.from,
        to: r.to,
        severity: filters.severity === "all" ? undefined : filters.severity,
        status: filters.statusFilter === "all" ? undefined : filters.statusFilter,
        category: filters.category === "all" ? undefined : filters.category,
      }),
    [
      refreshKey,
      filters.equipmentCodes.join(","),
      r.from,
      r.to,
      filters.severity,
      filters.statusFilter,
      filters.category,
    ]
  )
  const rows = data?.rows ?? []

  useEffect(() => {
    onExport?.({
      rows,
      columns: COLS,
      filename: `MinePulse_OEM_CodesErreur_${new Date().toISOString().slice(0, 10)}.xlsx`,
    })
  }, [rows, onExport])

  if (loading) return <OemEmptyState message="Chargement…" />
  if (error) return <OemEmptyState message={error} />
  return <OemGrid columns={COLS} rows={rows} />
}
