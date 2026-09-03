import type { ProductionRecord } from "@/lib/mock/types"

export type ProductionPaceStatus = "ahead" | "on_track" | "behind" | "unknown"

export const PACE_STATUS_LABEL: Record<ProductionPaceStatus, string> = {
  ahead: "En avance",
  on_track: "Proche de l’objectif",
  behind: "En retard",
  unknown: "Non évalué",
}

export type CumulativeProductionPoint = {
  hour: string
  actual: number | null
  target: number | null
  projected: number | null
  trips: number | null
  delayMin: number | null
  isProjection?: boolean
}

const ON_TRACK_RATIO = 0.97

export function parseHourLabel(label: string): number | null {
  const hour = Number.parseInt(String(label).slice(0, 2), 10)
  return Number.isFinite(hour) ? hour : null
}

export function parseShiftEndHour(label?: string | null): number | null {
  if (!label) return null
  const match = String(label).match(/(\d{1,2})\s*:\s*\d{2}\s*[–-]\s*(\d{1,2})\s*:\s*\d{2}/)
  if (!match) return null
  const end = Number.parseInt(match[2], 10)
  return Number.isFinite(end) ? end : null
}

/** Hours still to come after the last completed hourly bucket. Unknown if the shift end cannot be read. */
export function remainingShiftHours(
  hourly: ProductionRecord[],
  shiftEndHour: number | null,
): number | null {
  if (shiftEndHour == null || hourly.length === 0) return null
  const lastHour = parseHourLabel(hourly[hourly.length - 1]?.label ?? "")
  if (lastHour == null) return null
  return Math.max(0, shiftEndHour - 1 - lastHour)
}

export function productionPaceStatus(
  actualCum: number | null,
  targetCum: number | null,
): ProductionPaceStatus {
  if (actualCum == null || targetCum == null || targetCum <= 0) return "unknown"
  const ratio = actualCum / targetCum
  if (ratio >= 1) return "ahead"
  if (ratio >= ON_TRACK_RATIO) return "on_track"
  return "behind"
}

/** Minutes of production the cumulative gap represents at the observed hourly pace. Positive = retard. */
export function paceGapMinutes(
  actualCum: number | null,
  targetCum: number | null,
  elapsedHours: number,
): number | null {
  if (actualCum == null || targetCum == null || elapsedHours <= 0 || actualCum <= 0) return null
  const tonsPerHour = actualCum / elapsedHours
  if (tonsPerHour <= 0) return null
  return Math.round(((targetCum - actualCum) / tonsPerHour) * 60)
}

export function formatPaceGap(minutes: number | null): string {
  if (minutes == null) return "—"
  if (minutes > 0) return `Retard ${minutes} min`
  if (minutes < 0) return `Avance ${Math.abs(minutes)} min`
  return "À l’heure"
}

function nextHourLabel(label: string, offset: number): string {
  const hour = parseHourLabel(label)
  if (hour == null) return `${label}+${offset}`
  return `${String((hour + offset) % 24).padStart(2, "0")}:00`
}

function meanKnownHourlyTarget(hourly: ProductionRecord[]): number | null {
  const known = hourly.map((row) => row.target).filter((value): value is number => value != null)
  if (!known.length) return null
  return known.reduce((sum, value) => sum + value, 0) / known.length
}

/**
 * Running cumulative actual vs target. Missing hourly targets stay missing — they are never treated as 0.
 * Projected points are a linear continuation of the observed average hourly actual, only when remaining hours are known.
 */
export function buildCumulativeProductionSeries(
  hourly: ProductionRecord[],
  options?: { shiftEndHour?: number | null },
): {
  points: CumulativeProductionPoint[]
  lastActualCum: number | null
  lastTargetCum: number | null
  projectedEos: number | null
  remainingHours: number | null
  projectionKind: "measured" | "pace" | "unavailable"
} {
  let actualCum = 0
  let targetCum = 0
  let targetOk = true
  const measured: CumulativeProductionPoint[] = hourly.map((row) => {
    actualCum += row.tonnage
    if (row.target == null) targetOk = false
    else targetCum += row.target
    return {
      hour: row.label,
      actual: actualCum,
      target: targetOk ? targetCum : null,
      projected: null,
      trips: row.trips ?? null,
      delayMin: row.delayMin ?? null,
    }
  })

  const lastActualCum = measured.length ? actualCum : null
  const lastTargetCum = measured.length && targetOk ? targetCum : null
  const elapsedHours = measured.length
  const remainingHours = remainingShiftHours(hourly, options?.shiftEndHour ?? null)

  if (lastActualCum == null || elapsedHours <= 0) {
    return {
      points: measured,
      lastActualCum,
      lastTargetCum,
      projectedEos: null,
      remainingHours,
      projectionKind: "unavailable",
    }
  }

  if (remainingHours === 0) {
    return {
      points: measured,
      lastActualCum,
      lastTargetCum,
      projectedEos: lastActualCum,
      remainingHours,
      projectionKind: "measured",
    }
  }

  if (remainingHours == null || remainingHours <= 0) {
    return {
      points: measured,
      lastActualCum,
      lastTargetCum,
      projectedEos: null,
      remainingHours,
      projectionKind: "unavailable",
    }
  }

  const rate = lastActualCum / elapsedHours
  const projectedEos = Math.round(lastActualCum + rate * remainingHours)
  const lastLabel = hourly[hourly.length - 1]?.label ?? ""
  const plannedRate = meanKnownHourlyTarget(hourly)
  const last = measured[measured.length - 1]
  if (last) last.projected = lastActualCum

  const future: CumulativeProductionPoint[] = []
  for (let step = 1; step <= remainingHours; step += 1) {
    future.push({
      hour: nextHourLabel(lastLabel, step),
      actual: null,
      target: lastTargetCum != null && plannedRate != null ? Math.round(lastTargetCum + plannedRate * step) : null,
      projected: Math.round(lastActualCum + rate * step),
      trips: null,
      delayMin: null,
      isProjection: true,
    })
  }

  return {
    points: [...measured, ...future],
    lastActualCum,
    lastTargetCum,
    projectedEos,
    remainingHours,
    projectionKind: "pace",
  }
}
