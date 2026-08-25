import { Download, Loader2 } from "lucide-react"
import { useState } from "react"

import type { PerfAnalysis } from "@/lib/performance/metrics"
import { exportPerformanceWorkbook } from "@/lib/export/performanceXlsx"
import { Button } from "@/components/ui/button"

export function ExportExcelButton({
  analysis,
  visibleColumnIds,
  siteName,
  shiftLabel,
}: {
  analysis: PerfAnalysis
  visibleColumnIds?: string[]
  siteName?: string
  shiftLabel?: string
}) {
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)

  return (
    <div className="relative flex items-center gap-2">
      <Button
        size="sm"
        variant="outline"
        className="h-8 gap-1.5 text-[11px]"
        disabled={busy}
        onClick={() => {
          setBusy(true)
          setNotice(null)
          window.setTimeout(() => {
            const res = exportPerformanceWorkbook(analysis, {
              visibleColumnIds,
              siteName,
              shiftLabel,
            })
            setBusy(false)
            setNotice(res.ok ? `Exporté : ${res.filename}` : res.error ?? "Échec export")
            window.setTimeout(() => setNotice(null), 4000)
          }, 80)
        }}
      >
        {busy ? <Loader2 className="size-3.5 animate-spin" /> : <Download className="size-3.5" />}
        Export Excel
      </Button>
      {notice && (
        <span
          className="absolute right-0 top-full z-10 mt-1 whitespace-nowrap rounded-md border border-border bg-surface px-2 py-1 text-[10px] shadow-soft"
          role="status"
        >
          {notice}
        </span>
      )}
    </div>
  )
}
