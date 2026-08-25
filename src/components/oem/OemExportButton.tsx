import { useState } from "react"

import { exportOemWorkbook } from "@/lib/export/oemXlsx"
import type { OemCol } from "@/lib/oem/types"
import { Button } from "@/components/ui/button"

export function OemExportButton({
  rows,
  columns,
  context,
  filename,
  compact,
}: {
  rows: Record<string, unknown>[]
  columns: OemCol[]
  context: Record<string, string>
  filename: string
  compact?: boolean
}) {
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)

  function runExport() {
    setBusy(true)
    window.setTimeout(() => {
      const res = exportOemWorkbook({ filename, rows, columns, context })
      setBusy(false)
      setNotice(res.ok ? `Exporté : ${res.filename}` : res.error ?? "Échec")
      window.setTimeout(() => setNotice(null), 4000)
    }, 40)
  }

  return (
    <div className="relative">
      <Button
        type="button"
        variant="outline"
        size="sm"
        className={compact ? "h-7 w-full rounded-xl text-[11px]" : "h-7 rounded-xl text-[11px]"}
        disabled={busy || rows.length === 0}
        onClick={runExport}
      >
        {busy ? "Export…" : compact ? "Exporter vers Excel" : "Exporter Excel"}
      </Button>
      {notice ? (
        <span className="absolute bottom-full left-0 z-10 mb-1 whitespace-nowrap rounded-md border border-border bg-surface px-2 py-1 text-[10px] shadow-soft">
          {notice}
        </span>
      ) : null}
    </div>
  )
}
