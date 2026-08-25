import { useMemo, useState } from "react"
import { flexRender, type ColumnVisibilityState } from "@tanstack/react-table"
import { getCoreRowModel, useLegacyTable } from "@tanstack/react-table/legacy"
import { Columns3 } from "lucide-react"

import type { PerfAnalysis } from "@/lib/performance/metrics"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"

export function PerformanceTable({
  analysis,
  onVisibleColumnsChange,
}: {
  analysis: PerfAnalysis
  onVisibleColumnsChange?: (ids: string[]) => void
}) {
  const [visibility, setVisibility] = useState<ColumnVisibilityState>({})

  const columns = useMemo(
    () =>
      analysis.columns.map((c) => ({
        id: c.id,
        accessorKey: c.accessorKey,
        header: c.header,
        cell: (info: { getValue: () => unknown }) => {
          const v = info.getValue()
          if (v == null) return "—"
          return String(v)
        },
      })),
    [analysis.columns]
  )

  const table = useLegacyTable({
    data: analysis.rows,
    columns,
    state: { columnVisibility: visibility },
    onColumnVisibilityChange: (updater) => {
      setVisibility((prev: ColumnVisibilityState) => {
        const next = typeof updater === "function" ? updater(prev) : updater
        const ids = analysis.columns
          .filter((c) => next[c.id] !== false)
          .map((c) => c.id)
        onVisibleColumnsChange?.(ids)
        return next
      })
    },
    getCoreRowModel: getCoreRowModel(),
  })

  return (
    <div className="flex min-h-0 flex-col">
      <div className="mb-1.5 flex items-center justify-between">
        <h3 className="text-[12px] font-semibold text-foreground">Détail</h3>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button size="sm" variant="outline" className="h-7 gap-1 text-[11px]">
              <Columns3 className="size-3.5" />
              Colonnes
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-44">
            <DropdownMenuLabel className="text-[11px]">Colonnes visibles</DropdownMenuLabel>
            {table.getAllLeafColumns().map((col) => (
              <DropdownMenuCheckboxItem
                key={col.id}
                checked={col.getIsVisible()}
                onCheckedChange={(v) => col.toggleVisibility(!!v)}
                className="text-[11px]"
              >
                {typeof col.columnDef.header === "string" ? col.columnDef.header : col.id}
              </DropdownMenuCheckboxItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
      <div className="max-h-[280px] overflow-auto rounded-md border border-border">
        <table className="w-full text-left text-[11px]">
          <thead className="sticky top-0 bg-surface-2">
            {table.getHeaderGroups().map((hg) => (
              <tr key={hg.id}>
                {hg.headers.map((h) => (
                  <th
                    key={h.id}
                    className="whitespace-nowrap px-2.5 py-1.5 font-semibold text-muted-2"
                  >
                    {flexRender(h.column.columnDef.header, h.getContext())}
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows.map((row) => (
              <tr key={row.id} className="border-t border-border hover:bg-surface-2/60">
                {row.getVisibleCells().map((cell) => (
                  <td
                    key={cell.id}
                    className={cn(
                      "whitespace-nowrap px-2.5 py-1.5 tabular-nums text-foreground/90",
                      cell.column.id === "code" && "font-mono font-medium"
                    )}
                  >
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
