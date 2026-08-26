import { fmtDurationHms, fmtTsShort } from "@/lib/oem/format"
import { cn } from "@/lib/utils"

const COLORS: Record<string, string> = {
  online: "#78a828",
  disconnected: "#9aa3ad",
  unknown: "#d5d9de",
}

const LABELS: Record<string, string> = {
  online: "En ligne",
  disconnected: "Déconnecté",
  unknown: "Non déterminé",
}

export type PingRow = {
  code: string
  from?: string
  to?: string
  segments: Array<{ id: string; status: string; start: number; end: number }>
  connectedSec: number | null
  disconnectedSec: number | null
  unknownSec: number | null
  connectedPct?: number
}

export function OemConnectivityTimeline({ rows, showStats = true }: { rows: PingRow[]; showStats?: boolean }) {
  const allSegs = rows.flatMap((r) => r.segments)
  if (!allSegs.length) return <p className="p-3 text-xs text-muted">Historique de connectivité indisponible.</p>
  const t0 = Math.min(...allSegs.map((s) => s.start))
  const t1 = Math.max(...allSegs.map((s) => s.end))
  const span = Math.max(1, t1 - t0)
  const ticks = 8

  return (
    <div className={showStats ? "flex h-full min-h-0 flex-col bg-white" : "bg-white"}>
      <p className="shrink-0 border-b border-[#d0d5dc] px-2 py-1 text-[12px] font-semibold text-[#222]">
        Diagramme de ping
      </p>
      <div className={showStats ? "min-h-0 flex-1 overflow-auto px-2 py-2" : "px-2 py-2"}>
        <div className="mb-1 ml-[64px] flex justify-between text-[10px] text-[#6b7280]">
          {Array.from({ length: ticks + 1 }, (_, i) => {
            const t = t0 + (span * i) / ticks
            return <span key={i}>{fmtTsShort(new Date(t).toISOString())}</span>
          })}
        </div>
        {rows.map((row) => (
          <div key={row.code} className="mb-1.5 flex items-center gap-1.5">
            <span className="w-[64px] shrink-0 truncate text-[11px] font-medium">{row.code}</span>
            <div className="relative h-6 flex-1 overflow-hidden border border-[#d0d5dc] bg-[#eef0f3]">
              {row.segments.map((s) => {
                const left = ((s.start - t0) / span) * 100
                const width = Math.max(0.15, ((s.end - s.start) / span) * 100)
                return (
                  <div
                    key={s.id}
                    className="absolute top-0 h-full"
                    style={{
                      left: `${left}%`,
                      width: `${width}%`,
                      background: COLORS[s.status] ?? COLORS.unknown,
                    }}
                    title={LABELS[s.status] ?? s.status}
                  />
                )
              })}
            </div>
          </div>
        ))}

        <div className="mt-2 flex gap-3 text-[11px] text-[#4a5560]">
          <Legend c={COLORS.online} l="En ligne" />
          <Legend c={COLORS.disconnected} l="Déconnecté" />
          <Legend c={COLORS.unknown} l="Non déterminé" />
        </div>

        {showStats ? (
          <>
            <p className="mb-1 mt-4 text-[12px] font-semibold text-[#222]">
              Statistiques générales selon le régime de travail
            </p>
            <table className="w-full max-w-xl border-collapse text-[11px]">
              <thead>
                <tr className="bg-[#f3f5f7] text-left">
                  <th className="border border-[#d0d5dc] px-2 py-0.5 font-semibold">Engin</th>
                  <th className="border border-[#d0d5dc] px-2 py-0.5 font-semibold">En ligne</th>
                  <th className="border border-[#d0d5dc] px-2 py-0.5 font-semibold">Déconnecté</th>
                  <th className="border border-[#d0d5dc] px-2 py-0.5 font-semibold">Non déterminé</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.code}>
                    <td className="border border-[#d0d5dc] px-2 py-0.5">{row.code}</td>
                    <td className="border border-[#d0d5dc] px-2 py-0.5 tabular-nums">
                      {fmtDurationHms(row.connectedSec)}
                    </td>
                    <td className="border border-[#d0d5dc] px-2 py-0.5 tabular-nums">
                      {fmtDurationHms(row.disconnectedSec)}
                    </td>
                    <td className="border border-[#d0d5dc] px-2 py-0.5 tabular-nums">
                      {fmtDurationHms(row.unknownSec)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        ) : null}
      </div>
    </div>
  )
}

function Legend({ c, l }: { c: string; l: string }) {
  return (
    <span className={cn("flex items-center gap-1.5")}>
      <span className="inline-block size-3 border border-[#c5cad1]" style={{ background: c }} />
      {l}
    </span>
  )
}
