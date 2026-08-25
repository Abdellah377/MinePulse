import { ChevronDown, ChevronRight } from "lucide-react"
import { useEffect, useMemo, useState } from "react"

import { cn } from "@/lib/utils"
import type { Equipment } from "@/lib/mock/types"
import { OEM_TYPE_GROUP } from "@/lib/oem/types"

export function OemEquipmentTree({
  equipment,
  typeFilter,
  search,
  selected,
  onChange,
}: {
  equipment: Equipment[]
  typeFilter: string
  search: string
  selected: string[]
  onChange: (codes: string[]) => void
}) {
  const q = search.trim().toLowerCase()
  const [individualsOpen, setIndividualsOpen] = useState(() => Boolean(q))

  const groups = useMemo(() => {
    const map = new Map<string, Equipment[]>()
    for (const e of equipment) {
      if (typeFilter !== "all" && e.type !== typeFilter) continue
      if (q && !e.code.toLowerCase().includes(q) && !e.model.toLowerCase().includes(q)) continue
      const label = OEM_TYPE_GROUP[e.type] ?? e.type
      const list = map.get(label) ?? []
      list.push(e)
      map.set(label, list)
    }
    return [...map.entries()]
  }, [equipment, typeFilter, q])

  const visibleCodes = groups.flatMap(([, list]) => list.map((e) => e.code))
  const selectedVisible = selected.filter((c) => visibleCodes.includes(c))

  useEffect(() => {
    if (q) setIndividualsOpen(true)
  }, [q])

  return (
    <div className="flex flex-col gap-3">
      <div>
        <span className="mb-1 block text-[10px] font-semibold uppercase text-muted-2">Groupes</span>
        <div className="overflow-hidden rounded-xl border border-border bg-background text-[11px]">
          {groups.map(([label, list], i) => {
            const codes = list.map((e) => e.code)
            const allOn = codes.length > 0 && codes.every((c) => selected.includes(c))
            const some = codes.some((c) => selected.includes(c))
            return (
              <label
                key={label}
                className={cn(
                  "flex items-center gap-2 px-3 py-2",
                  i < groups.length - 1 && "border-b border-border",
                  allOn && "bg-accent-soft"
                )}
              >
                <input
                  type="checkbox"
                  className="accent-accent"
                  checked={allOn}
                  ref={(el) => {
                    if (el) el.indeterminate = some && !allOn
                  }}
                  onChange={() => {
                    if (allOn) onChange(selected.filter((c) => !codes.includes(c)))
                    else onChange([...new Set([...selected, ...codes])])
                  }}
                />
                {label}
                <span className="ml-auto text-muted-2">{list.length}</span>
              </label>
            )
          })}
          {groups.length === 0 ? <p className="px-3 py-2 text-muted-2">Aucun engin</p> : null}
        </div>
      </div>

      <div>
        <span className="mb-1 block text-[10px] font-semibold uppercase text-muted-2">Engins</span>
        <button
          type="button"
          className="flex h-7 w-full items-center rounded-xl border border-border bg-surface-2 px-3 text-left text-[11px] text-foreground hover:bg-surface-3"
          onClick={() => setIndividualsOpen((v) => !v)}
        >
          <span className="truncate">Sélection individuelle</span>
          <span className="ml-auto mr-1 shrink-0 text-[10px] text-muted-2">
            {selectedVisible.length}/{visibleCodes.length}
          </span>
          {individualsOpen ? (
            <ChevronDown className="size-3.5 shrink-0 text-muted" />
          ) : (
            <ChevronRight className="size-3.5 shrink-0 text-muted" />
          )}
        </button>
        {individualsOpen ? (
          <div className="mt-1 max-h-36 overflow-y-auto rounded-xl border border-border bg-background text-[11px]">
            {groups.flatMap(([, list]) =>
              list.map((e) => {
                const on = selected.includes(e.code)
                return (
                  <label
                    key={e.id}
                    className={cn(
                      "flex cursor-pointer items-center gap-2 border-b border-border px-3 py-1.5 last:border-b-0",
                      on && "bg-accent-soft"
                    )}
                  >
                    <input
                      type="checkbox"
                      className="accent-accent"
                      checked={on}
                      onChange={() => {
                        onChange(on ? selected.filter((c) => c !== e.code) : [...selected, e.code])
                      }}
                    />
                    <span className="truncate">{e.code}</span>
                  </label>
                )
              })
            )}
            {groups.length === 0 ? <p className="px-3 py-2 text-muted-2">Aucun engin</p> : null}
          </div>
        ) : null}
        <div className="mt-1 flex items-center justify-between text-[10px] text-muted">
          <button type="button" className="text-accent hover:underline" onClick={() => onChange(visibleCodes)}>
            Tout
          </button>
          <button type="button" className="text-accent hover:underline" onClick={() => onChange([])}>
            Aucun
          </button>
          <span>
            Sélectionnés {selectedVisible.length} de {visibleCodes.length}
          </span>
        </div>
      </div>
    </div>
  )
}
