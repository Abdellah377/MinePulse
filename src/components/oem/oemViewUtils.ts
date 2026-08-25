import { useEffect, useRef, useState } from "react"

import type { OemCol, OemDraft } from "@/lib/oem/types"
import { isoFromLocal, shiftBoundsIso } from "@/lib/oem/format"
import type { Shift } from "@/lib/mock/types"

export type OemExportPayload = {
  rows: Record<string, unknown>[]
  columns: OemCol[]
  filename: string
}

export type OemViewProps = {
  filters: OemDraft
  refreshKey: number
  siteName: string
  shiftLabel: string
  onOpenEquipment?: (code: string) => void
  onExport?: (payload: OemExportPayload | null) => void
  maxSignals?: number
}

export function rangeParams(
  filters: OemDraft,
  shifts: Shift[]
): { from?: string; to?: string } {
  if (filters.periodMode === "shift") return {}
  if (filters.periodMode === "custom") {
    return { from: isoFromLocal(filters.from), to: isoFromLocal(filters.to) }
  }
  const fromShift = shifts.find((s) => s.id === filters.fromShift) ?? shifts[0]
  const toShift = shifts.find((s) => s.id === filters.toShift) ?? fromShift
  if (!fromShift || !toShift) return {}
  const start = shiftBoundsIso(
    filters.fromDate,
    fromShift.startHour,
    fromShift.endHour,
    fromShift.startMinute,
    fromShift.endMinute
  )
  const end = shiftBoundsIso(
    filters.toDate || filters.fromDate,
    toShift.startHour,
    toShift.endHour,
    toShift.startMinute,
    toShift.endMinute
  )
  if (!start || !end) return {}
  return { from: start.from, to: end.to }
}

export function useOemLoad<T>(fn: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const fnRef = useRef(fn)
  fnRef.current = fn

  useEffect(() => {
    let cancelled = false
    let inFlight = false
    let first = true

    const run = () => {
      if (inFlight) return
      inFlight = true
      if (first) {
        setLoading(true)
        setError(null)
        setData(null)
      }
      fnRef
        .current()
        .then((d) => {
          if (!cancelled) {
            setData(d)
            setError(null)
          }
        })
        .catch((e: Error) => {
          if (!cancelled && first) setError(e.message || "Erreur API")
        })
        .finally(() => {
          inFlight = false
          if (!cancelled && first) {
            setLoading(false)
            first = false
          }
        })
    }

    run()
    const id = window.setInterval(run, 2500)
    return () => {
      cancelled = true
      window.clearInterval(id)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
  return { data, error, loading }
}

export function oemContext(filters: OemDraft, siteName: string, shiftLabel: string, extra?: Record<string, string>) {
  const engins = filters.equipmentCodes.length ? filters.equipmentCodes.join(", ") : "Tous"
  const period =
    filters.periodMode === "shift"
      ? "Poste actuel"
      : filters.periodMode === "posts"
        ? `${filters.fromDate} → ${filters.toDate}`
        : `${filters.from} → ${filters.to}`
  return {
    Site: siteName,
    Poste: shiftLabel,
    Engin: engins,
    Période: period,
    "Source données": "postgresql",
    Simulation: "true",
    Export: new Date().toLocaleString("fr-FR"),
    ...extra,
  }
}

export function codesQuery(codes: string[]): string | undefined {
  return codes.length ? codes.join(",") : undefined
}
