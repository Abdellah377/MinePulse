import * as XLSX from "xlsx"

import type { PerfAnalysis } from "@/lib/performance/metrics"
import { useApiMode } from "@/lib/api/client"
import { MERAH_SHIFT_SCENARIO } from "@/lib/mock/scenario"

export function exportPerformanceWorkbook(
  analysis: PerfAnalysis,
  options?: { siteName?: string; shiftLabel?: string; visibleColumnIds?: string[] }
): { filename: string; ok: boolean; error?: string } {
  try {
    const site = options?.siteName ?? (useApiMode ? "Site" : MERAH_SHIFT_SCENARIO.siteName)
    const shift = options?.shiftLabel ?? (useApiMode ? "Poste" : MERAH_SHIFT_SCENARIO.shiftLabel)
    const cols = analysis.columns.filter(
      (c) => !options?.visibleColumnIds || options.visibleColumnIds.includes(c.id)
    )

    const resultRows = analysis.rows.map((row) => {
      const out: Record<string, string | number | null> = {}
      for (const c of cols) {
        out[c.header] = (row[c.accessorKey] as string | number | null) ?? ""
      }
      return out
    })

    const contextRows = [
      { Champ: "Site", Valeur: site },
      { Champ: "Poste", Valeur: shift },
      { Champ: "Métrique", Valeur: analysis.title },
      { Champ: "Export", Valeur: new Date().toLocaleString("fr-FR") },
      { Champ: "Confiance IA", Valeur: `${analysis.interpretation.confidence} %` },
    ]

    const syntheseRows = [
      ...analysis.kpis.map((k) => ({
        Indicateur: k.label,
        Valeur: k.value,
        Note: k.hint ?? "",
      })),
      { Indicateur: "—", Valeur: "", Note: "" },
      {
        Indicateur: "Faits",
        Valeur: analysis.interpretation.facts.join(" · "),
        Note: "",
      },
      {
        Indicateur: "Inférence",
        Valeur: analysis.interpretation.inference,
        Note: "",
      },
      {
        Indicateur: "Manquant",
        Valeur: analysis.interpretation.missing.join(" · "),
        Note: "",
      },
    ]

    const wb = XLSX.utils.book_new()
    XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(resultRows), "Résultats")
    XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(contextRows), "Contexte")
    XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(syntheseRows), "Synthèse")

    const date = new Date().toISOString().slice(0, 10)
    const metricSlug = analysis.metric.charAt(0).toUpperCase() + analysis.metric.slice(1)
    const filename = `MinePulse_Performance_${metricSlug}_${date}.xlsx`
    XLSX.writeFile(wb, filename)
    return { filename, ok: true }
  } catch (e) {
    return {
      filename: "",
      ok: false,
      error: e instanceof Error ? e.message : "Export impossible",
    }
  }
}
