import { useEffect, useMemo, useRef, useState } from "react"
import { scopedOemApi } from "@/lib/api/oem"
import { useOpsStore } from "@/lib/store/useOpsStore"
import { analysisRangeIso } from "@/lib/ops/analysisWindow"
import { canonicalPosteName, type SelectedPoste } from "@/lib/ops/shiftLabel"
import { formatPeriodLabel } from "@/components/shared/PeriodFilters"

import type { OemCol, OemDraft } from "@/lib/oem/types"
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
  _filters: OemDraft,
  shifts: Shift[],
  periodFrom?: string,
  periodTo?: string,
  poste?: SelectedPoste,
  simNowIso?: string | null
): { from?: string; to?: string } {
  const from = periodFrom ?? useOpsStore.getState().periodFrom
  const to = periodTo ?? useOpsStore.getState().periodTo
  const selectedPoste = poste ?? useOpsStore.getState().selectedPoste
  const sim = simNowIso !== undefined ? simNowIso : useOpsStore.getState().simNowIso
  return analysisRangeIso(shifts, from, to, selectedPoste, sim)
}

export function useAnalysisRangeParams(): { from?: string; to?: string } {
  const shifts = useOpsStore((s) => s.shifts)
  const periodFrom = useOpsStore((s) => s.periodFrom)
  const periodTo = useOpsStore((s) => s.periodTo)
  const selectedPoste = useOpsStore((s) => s.selectedPoste)
  const simNowIso = useOpsStore((s) => s.simNowIso)
  return useMemo(
    () => analysisRangeIso(shifts, periodFrom, periodTo, selectedPoste, simNowIso),
    [shifts, periodFrom, periodTo, selectedPoste, simNowIso]
  )
}

export function useOemLoad<T>(fn: () => Promise<T>, deps: unknown[]) {
  const siteCode = useOpsStore((s) => s.selectedSiteId)
  const periodFrom = useOpsStore((s) => s.periodFrom)
  const periodTo = useOpsStore((s) => s.periodTo)
  const selectedPoste = useOpsStore((s) => s.selectedPoste)
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
  }, [...deps, siteCode, periodFrom, periodTo, selectedPoste])
  return { data, error, loading }
}

export function oemContext(filters: OemDraft, siteName: string, _shiftLabel: string, extra?: Record<string, string>) {
  const engins = filters.equipmentCodes.length ? filters.equipmentCodes.join(", ") : "Tous"
  const periodFrom = useOpsStore.getState().periodFrom
  const periodTo = useOpsStore.getState().periodTo
  const poste = useOpsStore.getState().selectedPoste
  const period = `${formatPeriodLabel(periodFrom, periodTo)} · ${canonicalPosteName(poste)}`
  return {
    Site: siteName,
    Poste: canonicalPosteName(poste),
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
