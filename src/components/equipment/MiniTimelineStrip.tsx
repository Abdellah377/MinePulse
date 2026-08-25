import type { TimelineSegment } from "@/lib/mock/types"
import { STATE_CONFIG } from "@/lib/status"
import { cn } from "@/lib/utils"

export function MiniTimelineStrip({
  segments,
  rangeStart,
  rangeEnd,
}: {
  segments: TimelineSegment[]
  rangeStart: number
  rangeEnd: number
}) {
  const total = Math.max(1, rangeEnd - rangeStart)
  return (
    <div className="flex h-6 w-full overflow-hidden rounded-none bg-surface-3">
      {segments.map((seg) => {
        const clippedStart = Math.max(seg.start, rangeStart)
        const clippedEnd = Math.min(seg.end, rangeEnd)
        const widthPct = ((clippedEnd - clippedStart) / total) * 100
        if (widthPct <= 0) return null
        return (
          <div
            key={seg.id}
            className={cn(STATE_CONFIG[seg.state].dot, "h-full rounded-none")}
            style={{ width: `${widthPct}%` }}
            title={`${STATE_CONFIG[seg.state].label}`}
          />
        )
      })}
    </div>
  )
}
