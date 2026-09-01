import type { Equipment, Shift, TimelineSegment } from "@/lib/mock/types"

import { posteFromShiftName, type SelectedPoste } from "./shiftLabel"

export const MAX_ANALYSIS_DAYS = 7

const DAY_MS = 86_400_000

export function operationalDateFromIso(iso: string | null | undefined): string | null {
  if (!iso) return null
  const ms = Date.parse(iso)
  if (!Number.isFinite(ms)) return null
  return new Date(ms).toISOString().slice(0, 10)
}

export function addUtcDays(ymd: string, days: number): string {
  const ms = Date.parse(`${ymd}T00:00:00.000Z`)
  if (!Number.isFinite(ms)) return ymd
  return new Date(ms + days * DAY_MS).toISOString().slice(0, 10)
}

/** Inclusive calendar period as `[from 00:00, to+1 00:00)` in UTC. */
export function periodBoundsMs(fromYmd: string, toYmd: string): { startMs: number; endMs: number } {
  const from = fromYmd <= toYmd ? fromYmd : toYmd
  const to = fromYmd <= toYmd ? toYmd : fromYmd
  return {
    startMs: Date.parse(`${from}T00:00:00.000Z`),
    endMs: Date.parse(`${addUtcDays(to, 1)}T00:00:00.000Z`),
  }
}

export function clampPeriodRange(from: string, to: string): { from: string; to: string } {
  const a = from <= to ? from : to
  const b = from <= to ? to : from
  const start = Date.parse(`${a}T00:00:00.000Z`)
  const end = Date.parse(`${b}T00:00:00.000Z`)
  if (!Number.isFinite(start) || !Number.isFinite(end)) return { from: a, to: b }
  const maxEnd = start + (MAX_ANALYSIS_DAYS - 1) * DAY_MS
  if (end > maxEnd) {
    return { from: a, to: new Date(maxEnd).toISOString().slice(0, 10) }
  }
  return { from: a, to: b }
}

function windowsOverlap(aStart: number, aEnd: number, bStart: number, bEnd: number): boolean {
  return aStart < bEnd && aEnd > bStart
}

function eachUtcDay(fromYmd: string, toYmd: string): string[] {
  const { from, to } = clampPeriodRange(fromYmd, toYmd)
  const days: string[] = []
  let cursor = from
  while (cursor <= to) {
    days.push(cursor)
    cursor = addUtcDays(cursor, 1)
  }
  return days
}

export function shiftSpanMs(
  shift: Shift,
  dayYmd?: string
): { startMs: number; endMs: number } | null {
  if (shift.windowStart && shift.windowEnd && !dayYmd) {
    const startMs = Date.parse(shift.windowStart)
    const endMs = Date.parse(shift.windowEnd)
    if (!Number.isFinite(startMs) || !Number.isFinite(endMs) || endMs <= startMs) return null
    return { startMs, endMs }
  }
  const day = dayYmd ?? (shift.windowStart ? new Date(Date.parse(shift.windowStart)).toISOString().slice(0, 10) : null)
  if (!day) return null
  const startMin = shift.startHour * 60 + (shift.startMinute ?? 0)
  const endMin = shift.endHour * 60 + (shift.endMinute ?? 0)
  const startMs = Date.parse(`${day}T00:00:00.000Z`) + startMin * 60_000
  let endMs = Date.parse(`${day}T00:00:00.000Z`) + endMin * 60_000
  if (endMs <= startMs) endMs += DAY_MS
  return { startMs, endMs }
}

function spansForShiftInPeriod(shift: Shift, fromYmd: string, toYmd: string): Array<{ startMs: number; endMs: number }> {
  if (shift.windowStart && shift.windowEnd) {
    const span = shiftSpanMs(shift)
    return span ? [span] : []
  }
  const from = fromYmd <= toYmd ? fromYmd : toYmd
  const to = fromYmd <= toYmd ? toYmd : fromYmd
  const days = eachUtcDay(addUtcDays(from, -1), to)
  const spans: Array<{ startMs: number; endMs: number }> = []
  for (const day of days) {
    const span = shiftSpanMs(shift, day)
    if (span) spans.push(span)
  }
  return spans
}

export function shiftsOverlappingPeriod(
  shifts: readonly Shift[],
  fromYmd: string,
  toYmd: string,
  poste: SelectedPoste = "all"
): Shift[] {
  const period = periodBoundsMs(fromYmd, toYmd)
  return shifts.filter((shift) => {
    if (poste !== "all" && posteFromShiftName(shift.name) !== poste) return false
    return spansForShiftInPeriod(shift, fromYmd, toYmd).some((span) =>
      windowsOverlap(span.startMs, span.endMs, period.startMs, period.endMs)
    )
  })
}

export type AnalysisWindow = {
  startMs: number
  endMs: number
  shifts: Shift[]
}

export function analysisWindowMs(
  shifts: readonly Shift[],
  fromYmd: string,
  toYmd: string,
  poste: SelectedPoste,
  simNowIso?: string | null
): AnalysisWindow | null {
  const matching = shiftsOverlappingPeriod(shifts, fromYmd, toYmd, poste)
  if (matching.length === 0) return null
  const period = periodBoundsMs(fromYmd, toYmd)
  const spans = matching.flatMap((shift) =>
    spansForShiftInPeriod(shift, fromYmd, toYmd).filter((span) =>
      windowsOverlap(span.startMs, span.endMs, period.startMs, period.endMs)
    )
  )
  if (spans.length === 0) return null
  let startMs = Math.min(...spans.map((s) => s.startMs))
  let endMs = Math.max(...spans.map((s) => s.endMs))
  const nowMs = simNowIso ? Date.parse(simNowIso) : Date.now()
  if (Number.isFinite(nowMs)) endMs = Math.min(endMs, nowMs)
  if (endMs - startMs > MAX_ANALYSIS_DAYS * DAY_MS) {
    startMs = endMs - MAX_ANALYSIS_DAYS * DAY_MS
  }
  if (!(endMs > startMs)) return null
  return { startMs, endMs, shifts: matching }
}

export function analysisRangeIso(
  shifts: readonly Shift[],
  fromYmd: string,
  toYmd: string,
  poste: SelectedPoste,
  simNowIso?: string | null
): { from: string; to: string } {
  const window = analysisWindowMs(shifts, fromYmd, toYmd, poste, simNowIso)
  if (window) {
    return { from: new Date(window.startMs).toISOString(), to: new Date(window.endMs).toISOString() }
  }
  const period = periodBoundsMs(fromYmd, toYmd)
  return { from: new Date(period.startMs).toISOString(), to: new Date(period.endMs).toISOString() }
}

export function segmentsIntersectingWindow(
  segments: readonly TimelineSegment[],
  startMs: number,
  endMs: number,
  equipmentIds?: ReadonlySet<string>
): TimelineSegment[] {
  return segments.filter((seg) => {
    if (seg.end < startMs || seg.start > endMs) return false
    if (equipmentIds && !equipmentIds.has(seg.equipmentId)) return false
    return true
  })
}

export function equipmentIdsMatching(
  equipment: ReadonlyArray<Pick<Equipment, "id" | "type" | "code">>,
  typeFilter: "all" | string,
  search: string
): Set<string> {
  const q = search.trim().toLowerCase()
  return new Set(
    equipment
      .filter((row) => typeFilter === "all" || row.type === typeFilter)
      .filter((row) => q === "" || row.code.toLowerCase().includes(q))
      .map((row) => row.id)
  )
}
