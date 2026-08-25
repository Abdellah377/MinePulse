import * as React from "react"

import { cn } from "@/lib/utils"
import { useOpsStore, type Density } from "@/lib/store/useOpsStore"

const TableDensityContext = React.createContext<Density>("compact")

function Table({ className, ...props }: React.ComponentProps<"table">) {
  const density = useOpsStore((s) => s.density)
  return (
    <TableDensityContext.Provider value={density}>
      <div className="relative w-full overflow-auto">
        <table
          data-slot="table"
          data-density={density}
          className={cn("w-full caption-bottom text-xs", className)}
          {...props}
        />
      </div>
    </TableDensityContext.Provider>
  )
}

function TableHeader({ className, ...props }: React.ComponentProps<"thead">) {
  return (
    <thead
      data-slot="table-header"
      className={cn(
        "sticky top-0 z-10 border-b border-border bg-surface",
        className
      )}
      {...props}
    />
  )
}

function TableBody({ className, ...props }: React.ComponentProps<"tbody">) {
  return (
    <tbody
      data-slot="table-body"
      className={cn("[&_tr:last-child]:border-0", className)}
      {...props}
    />
  )
}

function TableFooter({ className, ...props }: React.ComponentProps<"tfoot">) {
  return (
    <tfoot
      data-slot="table-footer"
      className={cn(
        "border-t border-border bg-surface-2 font-medium",
        className
      )}
      {...props}
    />
  )
}

function TableRow({ className, ...props }: React.ComponentProps<"tr">) {
  return (
    <tr
      data-slot="table-row"
      className={cn(
        "border-b border-border transition-colors hover:bg-surface-2/60 data-[state=selected]:bg-surface-3",
        className
      )}
      {...props}
    />
  )
}

function TableHead({ className, ...props }: React.ComponentProps<"th">) {
  const density = React.useContext(TableDensityContext)
  return (
    <th
      data-slot="table-head"
      className={cn(
        "whitespace-nowrap px-3 text-left align-middle text-[10px] font-semibold uppercase tracking-wider text-muted-2",
        density === "compact" ? "h-7" : "h-9",
        className
      )}
      {...props}
    />
  )
}

function TableCell({ className, ...props }: React.ComponentProps<"td">) {
  const density = React.useContext(TableDensityContext)
  return (
    <td
      data-slot="table-cell"
      className={cn(
        "whitespace-nowrap px-3 align-middle text-foreground/90",
        density === "compact" ? "py-1.5" : "py-3",
        className
      )}
      {...props}
    />
  )
}

function TableCaption({
  className,
  ...props
}: React.ComponentProps<"caption">) {
  return (
    <caption
      data-slot="table-caption"
      className={cn("mt-4 text-xs text-muted", className)}
      {...props}
    />
  )
}

export {
  Table,
  TableHeader,
  TableBody,
  TableFooter,
  TableHead,
  TableRow,
  TableCell,
  TableCaption,
}
