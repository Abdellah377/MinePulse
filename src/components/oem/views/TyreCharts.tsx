import { useOemApi } from "@/components/oem/oemViewUtils"
import { useOpsStore } from "@/lib/store/useOpsStore"
import { OemEmptyState } from "@/components/oem/OemEmptyState"
import { OemSynchronizedCharts } from "@/components/oem/OemSyncedCharts"
import { rangeParams, useOemLoad, type OemViewProps } from "@/components/oem/oemViewUtils"

export function TyreCharts({ filters, refreshKey }: OemViewProps) {
  const oemApi = useOemApi()
  const shifts = useOpsStore((s) => s.shifts)
  const code = filters.equipmentCodes[0]
  const r = rangeParams(filters, shifts)
  const pos = filters.tyrePositions.join(",")
  const { data, error, loading } = useOemLoad(
    () => (code ? oemApi.tyres(code, r.from, r.to, pos || undefined) : Promise.reject(new Error("Aucun engin"))),
    [refreshKey, code, r.from, r.to, pos]
  )
  if (!code) return <OemEmptyState message="Sélectionnez un camion, puis Actualiser." />
  if (loading) return <OemEmptyState message="Chargement…" />
  if (error) return <OemEmptyState message={error} />
  const msg = data?.message as string | undefined
  const points = (data?.points as Array<Record<string, unknown>>) ?? []
  const positions = (data?.positions as Array<{ code: string; labelFr: string }>) ?? []
  if (!points.length) return <OemEmptyState message={msg || "Aucune donnée pneu disponible pour cet engin."} />
  return (
    <OemSynchronizedCharts
      legendPosition="right"
      bandHeight={240}
      charts={[
        {
          title: "Pression",
          unit: "kPa",
          series: positions.map((p) => ({ key: `${p.code}_pressure`, name: p.labelFr })),
        },
        {
          title: "Température",
          unit: "°C",
          series: positions.map((p) => ({ key: `${p.code}_temp`, name: p.labelFr })),
        },
      ]}
      points={points}
      emptyMessage="Aucune donnée pneu disponible pour cet engin."
    />
  )
}
