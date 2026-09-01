import { useOpsStore } from "@/lib/store/useOpsStore"
import { operationalDateFromIso } from "@/lib/ops/analysisWindow"
import { POSTE_SELECTOR_OPTIONS, type SelectedPoste } from "@/lib/ops/shiftLabel"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"

/**
 * Shared Période + Poste filters for Film / Performance / OEM.
 * Date and poste are independent. Selector options never come from shift rows.
 */
export function PeriodFilters({ className }: { className?: string }) {
  const periodFrom = useOpsStore((s) => s.periodFrom)
  const periodTo = useOpsStore((s) => s.periodTo)
  const selectedPoste = useOpsStore((s) => s.selectedPoste)
  const simNowIso = useOpsStore((s) => s.simNowIso)
  const setPeriodRange = useOpsStore((s) => s.setPeriodRange)
  const setSelectedPoste = useOpsStore((s) => s.setSelectedPoste)
  const resetAnalysisFilters = useOpsStore((s) => s.resetAnalysisFilters)

  const operationalToday = operationalDateFromIso(simNowIso) ?? periodFrom
  const dirty =
    periodFrom !== operationalToday || periodTo !== operationalToday || selectedPoste !== "all"

  return (
    <div className={className}>
      <div className="mb-3">
        <label className="mb-1 block text-[10px] font-semibold uppercase tracking-wide text-muted-2">
          Période
        </label>
        <div className="flex flex-col gap-1.5">
          <label className="flex flex-col gap-0.5">
            <span className="text-[10px] text-muted-2">Du</span>
            <Input
              type="date"
              value={periodFrom}
              max={periodTo}
              onChange={(e) => setPeriodRange(e.target.value, periodTo)}
              className="h-8 rounded-md px-2 text-[12px]"
            />
          </label>
          <label className="flex flex-col gap-0.5">
            <span className="text-[10px] text-muted-2">Au</span>
            <Input
              type="date"
              value={periodTo}
              min={periodFrom}
              onChange={(e) => setPeriodRange(periodFrom, e.target.value)}
              className="h-8 rounded-md px-2 text-[12px]"
            />
          </label>
        </div>
      </div>

      <div className="mb-3">
        <label className="mb-1 block text-[10px] font-semibold uppercase tracking-wide text-muted-2">
          Poste
        </label>
        <Select value={selectedPoste} onValueChange={(v) => setSelectedPoste(v as SelectedPoste)}>
          <SelectTrigger className="h-8 w-full rounded-md text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {POSTE_SELECTOR_OPTIONS.map((option) => (
              <SelectItem key={option.id} value={option.id}>
                {option.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {dirty ? (
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="h-7 w-full justify-center px-2 text-[11px]"
          onClick={resetAnalysisFilters}
        >
          Réinitialiser les filtres
        </Button>
      ) : null}
    </div>
  )
}

export function formatPeriodLabel(from: string, to: string): string {
  if (!from || !to) return "—"
  if (from === to) {
    const [y, m, d] = from.split("-")
    return `${d}/${m}/${y}`
  }
  const fmt = (iso: string) => {
    const [y, m, d] = iso.split("-")
    return `${d}/${m}/${y}`
  }
  return `${fmt(from)} – ${fmt(to)}`
}
