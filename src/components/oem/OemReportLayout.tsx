import type { ReactNode } from "react"

import type { OemDraft } from "@/lib/oem/types"
import { oemViewTitle } from "@/lib/workspace/titles"
import { useOpsStore } from "@/lib/store/useOpsStore"
import { formatPeriodLabel } from "@/components/shared/PeriodFilters"
import { canonicalPosteName } from "@/lib/ops/shiftLabel"

/** Thin FMS-style context line: Entreprise: …; Engin: …; Intervalle: … */
export function OemReportContextBar({
  view,
  siteName,
  filters,
  extra,
}: {
  view: string
  siteName: string
  filters: OemDraft
  extra?: string
}) {
  const periodFrom = useOpsStore((s) => s.periodFrom)
  const periodTo = useOpsStore((s) => s.periodTo)
  const selectedPoste = useOpsStore((s) => s.selectedPoste)
  const engins = filters.equipmentCodes.length ? filters.equipmentCodes.join(", ") : "—"
  const interval = `${formatPeriodLabel(periodFrom, periodTo)} · ${canonicalPosteName(selectedPoste)}`
  const parts = [
    `Entreprise: ${siteName}`,
    `Engin: ${engins}`,
    `Intervalle: ${interval}`,
  ]
  if (filters.parameterKeys.length) {
    parts.push(`Paramètres: ${filters.parameterKeys.length} sélectionnés`)
  }
  if (extra) parts.push(extra)
  parts.push(oemViewTitle(view))

  return (
    <div className="oem-context shrink-0 border-b border-[#d0d5dc] bg-[#f7f8fa] px-2 py-1 text-[11px] leading-[16px] text-[#4a5560]">
      {parts.join("; ")}
    </div>
  )
}

/** @deprecated use OemReportContextBar */
export const OemContextLine = OemReportContextBar

export function OemReportLayout({
  panel,
  context,
  children,
}: {
  panel: ReactNode
  context: ReactNode
  children: ReactNode
}) {
  return (
    <div className="oem-shell flex h-full min-h-0 overflow-hidden bg-background">
      {panel}
      <div className="flex min-h-0 min-w-0 flex-1 flex-col bg-white">
        {context}
        <div className="min-h-0 flex-1 overflow-hidden">{children}</div>
      </div>
    </div>
  )
}
