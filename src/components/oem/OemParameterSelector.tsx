import { ChevronDown, ChevronRight } from "lucide-react"
import { useEffect, useState } from "react"

import type { OemCatalog } from "@/lib/api/oem"
import { cn } from "@/lib/utils"

export function OemParameterSelector({
  catalog,
  search,
  selected,
  onChange,
  equipmentType,
  maxSelected,
}: {
  catalog: OemCatalog | null
  search: string
  selected: string[]
  onChange: (keys: string[]) => void
  equipmentType?: string
  maxSelected?: number
}) {
  const q = search.trim().toLowerCase()
  const [open, setOpen] = useState(() => Boolean(q))

  const sensors = (catalog?.sensors ?? []).filter((s) => {
    if (s.source !== "telemetry") return false
    if (equipmentType && equipmentType !== "all") {
      const db = equipmentType === "haul_truck" ? "HAUL_TRUCK" : equipmentType.toUpperCase()
      if (!s.available_for.includes(db)) return false
    }
    if (q && !s.label_fr.toLowerCase().includes(q) && !s.key.toLowerCase().includes(q)) return false
    return true
  })
  const keys = sensors.map((s) => s.key)
  const selectedVisible = selected.filter((k) => keys.includes(k)).length

  useEffect(() => {
    if (q) setOpen(true)
  }, [q])

  return (
    <div className="flex flex-col">
      <button
        type="button"
        className="flex h-7 w-full items-center rounded-xl border border-border bg-surface-2 px-3 text-left text-[11px] text-foreground hover:bg-surface-3"
        onClick={() => setOpen((v) => !v)}
      >
        <span className="truncate">Paramètres</span>
        <span className="ml-auto mr-1 shrink-0 text-[10px] text-muted-2">
          {selectedVisible}/{keys.length}
        </span>
        {open ? (
          <ChevronDown className="size-3.5 shrink-0 text-muted" />
        ) : (
          <ChevronRight className="size-3.5 shrink-0 text-muted" />
        )}
      </button>
      {open ? (
        <div className="mt-1 max-h-36 overflow-y-auto rounded-xl border border-border bg-background text-[11px]">
          {sensors.map((s) => {
            const on = selected.includes(s.key)
            return (
              <label
                key={s.key}
                className={cn(
                  "flex cursor-pointer items-center gap-2 border-b border-border px-3 py-1.5 last:border-b-0",
                  on && "bg-accent-soft"
                )}
              >
                <input
                  type="checkbox"
                  className="accent-accent"
                  checked={on}
                  disabled={!on && maxSelected != null && selected.length >= maxSelected}
                  onChange={() => {
                    if (on) onChange(selected.filter((k) => k !== s.key))
                    else if (maxSelected == null || selected.length < maxSelected) onChange([...selected, s.key])
                  }}
                />
                <span className="truncate">
                  {s.label_fr}
                  <span className="text-muted-2"> ({s.unit})</span>
                </span>
              </label>
            )
          })}
          {sensors.length === 0 ? <p className="px-3 py-2 text-muted-2">Aucun paramètre</p> : null}
        </div>
      ) : null}
      <div className="mt-1 flex items-center justify-between text-[10px] text-muted">
        <button
          type="button"
          className="text-accent hover:underline"
          onClick={() => onChange(maxSelected != null ? keys.slice(0, maxSelected) : keys)}
        >
          Tout
        </button>
        <button type="button" className="text-accent hover:underline" onClick={() => onChange([])}>
          Aucun
        </button>
        <span>
          Sélectionnés {selectedVisible} de {keys.length}
        </span>
      </div>
    </div>
  )
}
