import { useOpsStore } from "@/lib/store/useOpsStore"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Input } from "@/components/ui/input"

/**
 * Shared poste + date-range filters for Film / Carte / Performance sidebars.
 */
export function PeriodFilters({ className }: { className?: string }) {
  const shifts = useOpsStore((s) => s.shifts)
  const selectedShiftId = useOpsStore((s) => s.selectedShiftId)
  const setSelectedShift = useOpsStore((s) => s.setSelectedShift)
  const periodFrom = useOpsStore((s) => s.periodFrom)
  const periodTo = useOpsStore((s) => s.periodTo)
  const setPeriodRange = useOpsStore((s) => s.setPeriodRange)

  return (
    <div className={className}>
      <div className="mb-3">
        <label className="mb-1 block text-[10px] font-semibold uppercase text-muted-2">Poste</label>
        <Select value={selectedShiftId} onValueChange={setSelectedShift}>
          <SelectTrigger className="h-7 w-full rounded-md text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {shifts.map((shift) => (
              <SelectItem key={shift.id} value={shift.id}>
                {shift.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="mb-3">
        <label className="mb-1 block text-[10px] font-semibold uppercase text-muted-2">
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
              className="h-7 rounded-md px-2 text-[11px]"
            />
          </label>
          <label className="flex flex-col gap-0.5">
            <span className="text-[10px] text-muted-2">Au</span>
            <Input
              type="date"
              value={periodTo}
              min={periodFrom}
              onChange={(e) => setPeriodRange(periodFrom, e.target.value)}
              className="h-7 rounded-md px-2 text-[11px]"
            />
          </label>
        </div>
      </div>
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
