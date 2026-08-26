import { useEffect, useMemo, useRef, useState } from "react"
import { scopedOemApi } from "@/lib/api/oem"
import { useOpsStore } from "@/lib/store/useOpsStore"

import type { OemCol, OemDraft } from "@/lib/oem/types"
import { isoFromLocal } from "@/lib/oem/format"
import type { Shift } from "@/lib/mock/types"

export const EMPTY_OEM_ROWS: Record<string, unknown>[] = []

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
    return { from: isoFromLocal(filters.from) ?? "unavailable", to: isoFromLocal(filters.to) ?? "unavailable" }
  }
  const fromShift = shifts.find((s) => s.id === filters.fromShift)
  const toShift = shifts.find((s) => s.id === filters.toShift)
  // Invalid values produce a controlled 422, never a silent different time window.
  return { from: fromShift?.windowStart ?? "unavailable", to: toShift?.windowEnd ?? "unavailable" }
}

export function useOemLoad<T>(fn: () => Promise<T>, deps: unknown[]) {
  const siteCode = useOpsStore((s) => s.selectedSiteId)
  const shiftId = useOpsStore((s) => s.selectedShiftId)
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
          if (!cancelled) { setError(e.message || "Erreur API"); setData(null) }
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
  }, [...deps, siteCode, shiftId])
  return { data, error, loading }
}

export function oemContext(filters: OemDraft, siteName: string, shiftLabel: string, extra?: Record<string, string>) {
  const engins = filters.equipmentCodes.length ? filters.equipmentCodes.join(", ") : "Tous"
  const period =
    filters.periodMode === "shift"
      ? "Poste sélectionné"
      : filters.periodMode === "posts"
        ? `${filters.fromShift} → ${filters.toShift} (fenêtres serveur)`
        : `${filters.from} → ${filters.to}`
  return {
    Site: siteName,
    Poste: shiftLabel,
    Engin: engins,
    Période: period,
    "Source données": "postgresql",
    "Mode données": "API opérationnelle",
    Export: new Date().toLocaleString("fr-FR"),
    ...extra,
  }
}

export function codesQuery(codes: string[]): string | undefined {
  return codes.length ? codes.join(",") : undefined
}

export function useOemApi() {
  const siteCode = useOpsStore((s) => s.selectedSiteId)
  const shiftId = useOpsStore((s) => s.selectedShiftId)
  return useMemo(() => scopedOemApi({ siteCode, shiftId }), [siteCode, shiftId])
}
