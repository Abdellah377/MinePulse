import { useOemApi } from "@/components/oem/oemViewUtils"
import { useOpsStore } from "@/lib/store/useOpsStore"
import { OemEmptyState } from "@/components/oem/OemEmptyState"
import { OemSynchronizedCharts } from "@/components/oem/OemSyncedCharts"
import { rangeParams, useOemLoad, type OemViewProps } from "@/components/oem/oemViewUtils"

export function SpeedFuelCharts({ filters, refreshKey }: OemViewProps) {
  const oemApi = useOemApi()
  const shifts = useOpsStore((s) => s.shifts)
  const code = filters.equipmentCodes[0]
  const r = rangeParams(filters, shifts)
  const { data, error, loading } = useOemLoad(
    () =>
      code
        ? oemApi.telemetry(code, "fuel_level_pct,speed_kmh", r.from, r.to)
        : Promise.reject(new Error("Aucun engin")),
    [refreshKey, code, r.from, r.to]
  )
  if (!code) return <OemEmptyState message="Sélectionnez un engin, puis Actualiser." />
  if (loading) return <OemEmptyState message="Chargement…" />
  if (error) return <OemEmptyState message={error} />
  const points = (data?.points as Array<Record<string, unknown>>) ?? []
  return (
    <OemSynchronizedCharts
      bandHeight={260}
      charts={[
        {
          title: "Le niveau de carburant",
          unit: "%",
          series: [{ key: "fuel_level_pct", name: "Niveau carburant", color: "#3a7bd5" }],
        },
        {
          title: "Vitesse",
          unit: "km/h",
          series: [{ key: "speed_kmh", name: "Vitesse", color: "#e8c800" }],
        },
      ]}
      points={points}
      emptyMessage="Aucune donnée disponible pour ce paramètre."
    />
  )
}
