import { useMemo, useState } from "react"

import { cn } from "@/lib/utils"
import { fmtDurationHms, fmtTs } from "@/lib/oem/format"
import type { OemCol } from "@/lib/oem/types"
import { UNAVAILABLE_SIM } from "@/lib/oem/types"

const PAGE = 200

export function OemGrid({
  columns,
  rows,
  search,
  onRowClick,
}: {
  columns: OemCol[]
  rows: Record<string, unknown>[]
  search?: string
  onRowClick?: (row: Record<string, unknown>) => void
}) {
  const [sortKey, setSortKey] = useState<string | null>(null)
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc")
  const [page, setPage] = useState(0)

  const visible = columns.filter((c) => c.defaultVisible !== false)
  const filtered = useMemo(() => {
    const q = (search ?? "").trim().toLowerCase()
    let list = rows
    if (q) {
      list = list.filter((r) => Object.values(r).some((v) => String(v ?? "").toLowerCase().includes(q)))
    }
    if (sortKey) {
      list = [...list].sort((a, b) => {
        const av = a[sortKey]
        const bv = b[sortKey]
        if (av == null || av === "") return 1
        if (bv == null || bv === "") return -1
        const cmp = av < bv ? -1 : av > bv ? 1 : 0
        return sortDir === "asc" ? cmp : -cmp
      })
    }
    return list
  }, [rows, search, sortKey, sortDir])

  const pages = Math.max(1, Math.ceil(filtered.length / PAGE))
  const slice = filtered.length > PAGE ? filtered.slice(page * PAGE, page * PAGE + PAGE) : filtered

  return (
    <div className="flex min-h-0 flex-1 flex-col bg-white">
      <div className="min-h-0 flex-1 overflow-auto">
        <table className="w-full border-collapse text-[11px] leading-[20px]">
          <thead className="sticky top-0 z-10">
            <tr>
              {visible.map((c) => (
                <th
                  key={c.id}
                  className={cn(
                    "h-6 border-b border-[#d0d5dc] bg-[#f3f5f7] px-1.5 text-left font-semibold text-[#4a5560]",
                    c.align === "right" && "text-right",
                    "cursor-pointer select-none whitespace-nowrap"
                  )}
                  onClick={() => {
                    if (sortKey === c.id) setSortDir((d) => (d === "asc" ? "desc" : "asc"))
                    else {
                      setSortKey(c.id)
                      setSortDir("asc")
                    }
                  }}
                >
                  {c.header}
                  {sortKey === c.id ? (sortDir === "asc" ? " ↑" : " ↓") : ""}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {slice.length === 0 ? (
              <tr>
                <td colSpan={visible.length} className="px-2 py-4 text-left text-[#6b7280]">
                  Aucune donnée.
                </td>
              </tr>
            ) : (
              slice.map((row, i) => (
                <tr
                  key={i}
                  className={cn(
                    "h-5",
                    i % 2 === 1 ? "bg-[#f7f8fa]" : "bg-white",
                    onRowClick && "cursor-pointer hover:bg-[#eef6e8]"
                  )}
                  onClick={() => onRowClick?.(row)}
                >
                  {visible.map((c) => (
                    <td
                      key={c.id}
                      className={cn(
                        "whitespace-nowrap border-b border-[#eceff2] px-1.5 py-0 tabular-nums",
                        c.align === "right" && "text-right"
                      )}
                    >
                      <Cell col={c} value={row[c.id]} />
                    </td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
      <div className="flex h-5 shrink-0 items-center justify-between border-t border-[#d0d5dc] bg-[#f3f5f7] px-2 text-[10px] text-[#5f6b74]">
        <span>
          {filtered.length} ligne{filtered.length > 1 ? "s" : ""}
        </span>
        {filtered.length > PAGE ? (
          <span className="flex items-center gap-2">
            <button type="button" disabled={page <= 0} onClick={() => setPage((p) => p - 1)}>
              ‹
            </button>
            Page {page + 1} / {pages}
            <button type="button" disabled={page >= pages - 1} onClick={() => setPage((p) => p + 1)}>
              ›
            </button>
          </span>
        ) : null}
      </div>
    </div>
  )
}

function Cell({ col, value }: { col: OemCol; value: unknown }) {
  if (col.unavailable) {
    return (
      <span className="text-[#9ca3af]" title={col.unavailableReason ?? UNAVAILABLE_SIM}>
        —
      </span>
    )
  }
  if (value == null || value === "") {
    return <span className="text-[#9ca3af]">—</span>
  }
  let text = String(value)
  if (typeof value === "string" && /^\d{4}-\d{2}-\d{2}T/.test(value)) text = fmtTs(value)
  if (col.tone === "delay" && typeof value === "number") {
    text = fmtDurationHms(value)
    return <span>{text || "—"}</span>
  }
  if ((col.tone === "alarm-red" || col.tone === "alarm-yellow") && (value === 0 || value === "0")) {
    return <span className="text-[#9ca3af]">0</span>
  }
  if (col.tone === "alarm-red" && Number(value) > 0) {
    return <span className="font-medium text-[#d82010]">{text}</span>
  }
  if (col.tone === "alarm-yellow" && Number(value) > 0) {
    return <span className="font-medium text-[#b8860b]">{text}</span>
  }
  return <>{text}</>
}

export { OemGrid as OemDataTable }
