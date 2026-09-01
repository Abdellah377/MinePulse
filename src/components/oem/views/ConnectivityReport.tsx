import { useEffect, useMemo } from "react"

import { useOemApi } from "@/components/oem/oemViewUtils"
import type { OemCol } from "@/lib/oem/types"
import { OemGrid } from "@/components/oem/OemDataTable"
import { OemEmptyState } from "@/components/oem/OemEmptyState"
import { OemConnectivityTimeline, type PingRow } from "@/components/oem/OemConnectivityTimeline"
import { useAnalysisRangeParams, useOemLoad, type OemViewProps } from "@/components/oem/oemViewUtils"
import { useOpsStore } from "@/lib/store/useOpsStore"

const STATUS: Record<string, string> = {
  online: "En ligne",
  delayed: "Retard",
  disconnected: "Déconnecté",
  unknown: "Aucune donnée",
}

const COLS: OemCol[] = [
  { id: "code", header: "Engin" },
  { id: "type", header: "Type" },
  { id: "commStatusLabel", header: "État communication" },
  { id: "lastTelemetry", header: "Dernière télémétrie" },
  { id: "lastPosition", header: "Dernière position" },
  { id: "currentDelaySec", header: "Retard actuel", tone: "delay", align: "right" },
  { id: "meanDelaySec", header: "Retard moyen", tone: "delay", align: "right" },
  { id: "maxDelaySec", header: "Retard maximal", tone: "delay", align: "right" },
  { id: "connectedSec", header: "Durée en ligne", tone: "delay", align: "right" },
  { id: "disconnectedSec", header: "Durée déconnecté", tone: "delay", align: "right" },
  { id: "unknownSec", header: "Durée non déterminée", tone: "delay", align: "right" },
  { id: "commQuality", header: "Qualité communication", align: "right" },
  { id: "incidentCount", header: "Nombre de coupures", align: "right" },
]

type ConnBundle = {
  ping: { rows: Array<Record<string, unknown>> }
  conn: { rows: Array<Record<string, unknown>> }
  delay: { rows: Array<Record<string, unknown>> }
}

export function ConnectivityReport({ filters, refreshKey, onOpenEquipment, onExport }: OemViewProps) {
  const oemApi = useOemApi()
  const siteCode = useOpsStore((s) => s.selectedSiteId)
  const codes = filters.equipmentCodes
  const r = useAnalysisRangeParams()
  const { data, error, loading } = useOemLoad<ConnBundle>(
    () =>
      Promise.all([
        codes.length
          ? oemApi.pingFleet(codes.join(","), r.from, r.to, siteCode)
          : Promise.resolve({ rows: [] as Array<Record<string, unknown>> }),
        oemApi.connectivity(r.from, r.to, siteCode),
        oemApi.delays(0, r.from, r.to, siteCode),
      ]).then(([ping, conn, delay]) => ({ ping, conn, delay })),
    [refreshKey, codes.join(","), r.from, r.to, siteCode]
  )

  const pingRows = useMemo(() => {
    return ((data?.ping.rows ?? []) as PingRow[]).map((row) => ({
      ...row,
      segments: (row.segments ?? []) as PingRow["segments"],
      connectedSec: row.connectedSec ?? null,
      disconnectedSec: row.disconnectedSec ?? null,
      unknownSec: row.unknownSec ?? null,
    }))
  }, [data])

  const tableRows = useMemo(() => {
    const connBy = new Map((data?.conn.rows ?? []).map((row) => [String(row.code), row]))
    const delayBy = new Map((data?.delay.rows ?? []).map((row) => [String(row.code), row]))
    const pingBy = new Map(pingRows.map((row) => [row.code, row]))
    return codes.map((code) => {
      const c = connBy.get(code) ?? {}
      const d = delayBy.get(code) ?? {}
      const p = pingBy.get(code)
      const status = String(c.commStatus ?? d.status ?? "")
      return {
        code,
        type: c.type ?? "",
        commStatusLabel: STATUS[status] ?? status,
        lastTelemetry: c.lastTelemetry ?? d.lastTelemetry,
        lastPosition: c.lastPosition ?? d.lastPosition,
        currentDelaySec: d.currentDelaySec ?? c.telemetryDelaySec,
        meanDelaySec: d.meanDelaySec,
        maxDelaySec: d.maxDelaySec,
        connectedSec: p?.connectedSec,
        disconnectedSec: p?.disconnectedSec,
        unknownSec: p?.unknownSec,
        commQuality: c.commQuality,
        incidentCount: d.incidentCount,
      } as Record<string, unknown>
    }).filter((row) => filters.minDelaySec <= 0 || (typeof row.currentDelaySec === "number" && row.currentDelaySec > filters.minDelaySec))
  }, [data, codes, pingRows, filters.minDelaySec])

  useEffect(() => {
    onExport?.({
      rows: tableRows,
      columns: COLS,
      filename: `MinePulse_OEM_Connectivite_${new Date().toISOString().slice(0, 10)}.xlsx`,
    })
  }, [onExport, tableRows])

  if (!codes.length) return <OemEmptyState message="Sélectionnez un engin, puis Actualiser." />
  if (loading && !data) return <OemEmptyState message="Chargement…" />
  if (error && !data) return <OemEmptyState message={error} />

  return (
    <div className="flex h-full min-h-0 flex-col bg-white">
      <div className="max-h-[45%] shrink-0 overflow-auto border-b border-[#d0d5dc]">
        {pingRows.length ? (
          <OemConnectivityTimeline rows={pingRows} showStats={false} />
        ) : (
          <OemEmptyState message="Aucune donnée de connectivité sur cette période." />
        )}
      </div>
      <p className="shrink-0 border-b border-[#d0d5dc] bg-[#f3f5f7] px-2 py-0.5 text-[11px] font-semibold text-[#222]">
        Communication / retard {filters.minDelaySec > 0 ? `> ${filters.minDelaySec} s (valeurs connues)` : "— tous les engins sélectionnés"}
      </p>
      <OemGrid columns={COLS} rows={tableRows} onRowClick={(row) => onOpenEquipment?.(String(row.code))} />
    </div>
  )
}
