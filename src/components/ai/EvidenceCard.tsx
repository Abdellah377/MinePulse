import { Activity, ArrowDown, ArrowUp, Minus } from "lucide-react"

import type { EvidenceSummary } from "@/lib/ai/investigationReport"
import { formatInvestigationTime } from "@/lib/ai/investigationReport"
import { cn } from "@/lib/utils"

export const DISCLOSURE_SUMMARY_CLASS =
  "cursor-pointer select-none rounded-sm px-3 py-2.5 text-[11px] font-semibold text-foreground outline-none focus-visible:ring-2 focus-visible:ring-accent/40 focus-visible:ring-offset-2 focus-visible:ring-offset-background"

function DirectionIcon({ direction }: { direction: EvidenceSummary["direction"] }) {
  if (direction === "up") return <ArrowUp aria-label="Hausse" className="size-4 text-warning" />
  if (direction === "down") return <ArrowDown aria-label="Baisse" className="size-4 text-accent" />
  if (direction === "stable") return <Minus aria-label="Stable" className="size-4 text-muted" />
  return <Activity aria-hidden="true" className="size-4 text-muted-2" />
}

export function EvidenceCard({
  item,
  markSummary = false,
}: {
  item: EvidenceSummary
  markSummary?: boolean
}) {
  return (
    <article
      {...(markSummary ? { "data-evidence-summary": "true" } : {})}
      className="rounded-md border border-border bg-surface px-3 py-2.5"
    >
      <div className="flex items-start gap-2">
        <DirectionIcon direction={item.direction} />
        <div className="min-w-0">
          <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-2">{item.label}</p>
          <p className={cn("mt-0.5 text-[13px] font-semibold tabular-nums", !item.available && "text-muted")}>
            {item.value}
          </p>
          {item.meaning && <p className="mt-0.5 text-[11px] text-muted">{item.meaning}</p>}
          {item.sampleCount != null && (
            <p className="mt-0.5 text-[10px] text-muted-2">{item.sampleCount} mesures</p>
          )}
          {item.timestamp && (
            <time className="mt-1 block text-[10px] tabular-nums text-muted-2" dateTime={item.timestamp}>
              {formatInvestigationTime(item.timestamp)}
            </time>
          )}
          {item.why && <p className="mt-1 text-[11px] text-foreground/80">→ {item.why}</p>}
        </div>
      </div>
    </article>
  )
}

export function PrimaryEvidenceGrid({
  items,
  markSummary = false,
}: {
  items: EvidenceSummary[]
  markSummary?: boolean
}) {
  return (
    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
      {items.map((item) => (
        <EvidenceCard key={item.key} item={item} markSummary={markSummary} />
      ))}
    </div>
  )
}
