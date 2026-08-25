import * as XLSX from "xlsx"

export function exportOemWorkbook(opts: {
  filename: string
  rows: Record<string, unknown>[]
  columns: Array<{ id: string; header: string }>
  context: Record<string, string>
}): { filename: string; ok: boolean; error?: string } {
  try {
    const resultRows = opts.rows.map((row) => {
      const out: Record<string, string | number | null> = {}
      for (const c of opts.columns) {
        const v = row[c.id]
        out[c.header] = v == null ? "" : (v as string | number)
      }
      return out
    })
    const contextRows = Object.entries(opts.context).map(([Champ, Valeur]) => ({ Champ, Valeur }))
    const wb = XLSX.utils.book_new()
    XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(resultRows), "Résultats")
    XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(contextRows), "Contexte")
    XLSX.writeFile(wb, opts.filename)
    return { filename: opts.filename, ok: true }
  } catch (e) {
    return { filename: "", ok: false, error: e instanceof Error ? e.message : "Export impossible" }
  }
}
