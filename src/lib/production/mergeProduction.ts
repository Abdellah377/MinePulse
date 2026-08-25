import type { ProductionRecord } from "@/lib/mock/types"

export type ProductionByShift = {
  hourly: ProductionRecord[]
  daily: ProductionRecord[]
  shiftly: ProductionRecord[]
}

export function isValidProductionByShift(
  value: unknown
): value is ProductionByShift {
  if (!value || typeof value !== "object") return false
  const v = value as Record<string, unknown>
  return (
    Array.isArray(v.hourly) &&
    Array.isArray(v.daily) &&
    Array.isArray(v.shiftly)
  )
}

/** Never replace valid production state with lite `{}` or partial payloads. */
export function mergeProductionByShift(
  prev: ProductionByShift,
  incoming: unknown
): ProductionByShift {
  if (!incoming) return prev
  if (!isValidProductionByShift(incoming)) return prev
  return incoming
}

/** Read authoritative shift rollup from backend DTO (API mode). */
export function shiftProductionRollup(production: ProductionByShift) {
  const row = production.shiftly[0]
  if (!row) {
    return {
      actual: null as number | null,
      target: null as number | null,
      attainmentPct: null as number | null,
      gapTons: null as number | null,
      gapPct: null as number | null,
      targetCycleMin: null as number | null,
      label: "—",
    }
  }
  const tonnage = row.tonnage
  const target = row.target ?? null
  return {
    actual: tonnage,
    target,
    attainmentPct: row.attainmentPct ?? null,
    gapTons: row.gapTons ?? null,
    gapPct: row.gapPct ?? null,
    targetCycleMin: row.targetCycleMin ?? null,
    label: row.label ?? "—",
  }
}

export type ShiftProductionRollup = ReturnType<typeof shiftProductionRollup>

/** Objectif display — missing target is "—", never "0 t". */
export function formatRollupTarget(rollup: ShiftProductionRollup): string {
  if (rollup.target == null) return "—"
  return `${rollup.target.toLocaleString("fr-FR")} t`
}

/** Actual tonnes this shift. Missing shift row is "—"; 0 is a measured zero. */
export function formatRollupActual(rollup: ShiftProductionRollup): string {
  if (rollup.actual == null) return "—"
  return `${rollup.actual.toLocaleString("fr-FR")} t`
}

/** Attainment display — unknown is "—", never "0%". */
export function formatRollupAttainment(rollup: ShiftProductionRollup): string {
  if (rollup.attainmentPct == null) return "—"
  return `${Number(rollup.attainmentPct).toFixed(0)} %`
}

export function formatPosteBarObjectif(rollup: ShiftProductionRollup): string {
  if (rollup.attainmentPct == null) return "—"
  return `${rollup.attainmentPct.toFixed(0)}% objectif`
}
