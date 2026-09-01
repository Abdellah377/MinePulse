import { useOemApi } from "@/components/oem/oemViewUtils"
import { OemEmptyState } from "@/components/oem/OemEmptyState"
import { OemSynchronizedCharts } from "@/components/oem/OemSyncedCharts"
import { useAnalysisRangeParams, useOemLoad, type OemViewProps } from "@/components/oem/oemViewUtils"

const FALLBACK = [
  { key: "speed_kmh", label: "Vitesse", unit: "km/h" },
  { key: "fuel_level_pct", label: "Niveau carburant", unit: "%" },
  { key: "fuel_rate_lph", label: "Consommation carburant", unit: "l/h" },
  { key: "payload_t", label: "Charge utile", unit: "t" },
  { key: "engine_temp_c", label: "Température moteur", unit: "°C" },
  { key: "coolant_temp_c", label: "Température liquide refroidissement", unit: "°C" },
  { key: "oil_pressure_kpa", label: "Pression huile", unit: "kPa" },
  { key: "engine_rpm", label: "Régime moteur", unit: "tr/min" },
  { key: "engine_load_pct", label: "Charge moteur", unit: "%" },
  { key: "battery_voltage", label: "Tension batterie", unit: "V" },
  { key: "communication_quality", label: "Qualité communication", unit: "%" },
]

export function AnalyseCharts({ filters, refreshKey, maxSignals = 4 }: OemViewProps) {
  return (
    <SignalWorkspace
      filters={filters}
      refreshKey={refreshKey}
      defaultKeys={["engine_temp_c", "oil_pressure_kpa", "battery_voltage"]}
      maxSignals={maxSignals}
    />
  )
}

export function MultiSignalExplorer({ filters, refreshKey }: OemViewProps) {
  return (
    <SignalWorkspace
      filters={filters}
      refreshKey={refreshKey}
      defaultKeys={["engine_temp_c", "oil_pressure_kpa", "battery_voltage"]}
    />
  )
}

function SignalWorkspace({
  filters,
  refreshKey,
  defaultKeys,
  maxSignals,
}: Pick<OemViewProps, "filters" | "refreshKey"> & { defaultKeys: string[]; maxSignals?: number }) {
  const oemApi = useOemApi()
  const code = filters.equipmentCodes[0]
  const selected = filters.parameterKeys.length ? filters.parameterKeys : defaultKeys
  const keys = maxSignals ? selected.slice(0, maxSignals) : selected
  const r = useAnalysisRangeParams()
  const { data, error, loading } = useOemLoad(
    () => (code ? oemApi.telemetry(code, keys.join(","), r.from, r.to) : Promise.reject(new Error("Aucun engin"))),
    [refreshKey, code, keys.join(","), r.from, r.to]
  )
  if (!code) return <OemEmptyState message="Sélectionnez un engin, puis Actualiser." />
  if (!keys.length) {
    return <OemEmptyState message="Sélectionnez au moins un paramètre, puis Actualiser." />
  }
  if (loading) return <OemEmptyState message="Chargement…" />
  if (error) return <OemEmptyState message={error} />
  const unavailable = (data?.unavailable as string[]) ?? []
  const points = (data?.points as Array<Record<string, unknown>>) ?? []
  const signalMeta = (data?.signals as Array<{ key: string; labelFr: string; unit: string }>) ?? []
  const charts = keys.map((k) => {
    const meta = signalMeta.find((s) => s.key === k)
    const fb = FALLBACK.find((o) => o.key === k)
    return {
      title: meta?.labelFr ?? fb?.label ?? k,
      unit: meta?.unit ?? fb?.unit ?? "",
      series: [{ key: k, name: meta?.labelFr ?? fb?.label ?? k }],
    }
  })
  return (
    <div className="flex h-full min-h-0 flex-col bg-white">
      {unavailable.length ? (
        <p className="border-b border-[#d0d5dc] px-2 py-1 text-[11px] text-[#6b7280]">
          Aucune donnée disponible pour ce paramètre. ({unavailable.join(", ")})
        </p>
      ) : null}
      {maxSignals && selected.length > maxSignals ? (
        <p className="border-b border-[#d0d5dc] px-2 py-1 text-[11px] text-[#6b7280]">
          Analyse limitée à {maxSignals} paramètres (sélection dans le panneau de gauche).
        </p>
      ) : null}
      <OemSynchronizedCharts
        charts={charts}
        points={points}
        emptyMessage="Aucune donnée disponible pour ce paramètre."
        bandHeight={keys.length > 4 ? 140 : undefined}
      />
    </div>
  )
}
