import type { Equipment, ProductionRecord, Zone } from "@/lib/mock/types"
import { MERAH_SHIFT_SCENARIO, SPOTLIGHT, type ShiftScenario } from "@/lib/mock/scenario"
import { useApiMode } from "@/lib/api/client"

export interface ShiftProduction {
  actual: number
  target: number
  attainmentPct: number
  gapTons: number
  gapPct: number
  hourly: ProductionRecord[]
}

/** Hours belonging to the morning shift [06:00, 14:00). */
export function isMorningShiftHour(label: string): boolean {
  const h = Number.parseInt(label.slice(0, 2), 10)
  return Number.isFinite(h) && h >= 6 && h < 14
}

/** Slice production to the active morning shift — mock only. */
export function getShiftHourly(hourly: ProductionRecord[]): ProductionRecord[] {
  if (useApiMode) return hourly
  const sliced = hourly.filter((r) => isMorningShiftHour(r.label))
  if (sliced.length > 0) return sliced
  // Fallback coherent series if store was emptied (LOCAL_MOCK only)
  return [
    { label: "06:00", tonnage: 900, target: 1020 },
    { label: "07:00", tonnage: 980, target: 1020 },
    { label: "08:00", tonnage: 1020, target: 1020 },
    { label: "09:00", tonnage: 960, target: 1020 },
    { label: "10:00", tonnage: 880, target: 1020 },
    { label: "11:00", tonnage: 780, target: 1020 },
    { label: "12:00", tonnage: 800, target: 1020 },
    { label: "13:00", tonnage: 911, target: 1020 },
  ]
}

export function getShiftProduction(
  hourly: ProductionRecord[],
  scenario: ShiftScenario = MERAH_SHIFT_SCENARIO
): ShiftProduction {
  if (useApiMode) {
    throw new Error("getShiftProduction is mock-only; use shiftProductionRollup in API mode")
  }

  const shiftHours = getShiftHourly(hourly)
  const summedActual = shiftHours.reduce((s, r) => s + r.tonnage, 0)
  const summedTarget = shiftHours.reduce((s, r) => s + (r.target ?? 0), 0)

  // Prefer canonical scenario totals so every screen agrees (LOCAL_MOCK)
  const actual = scenario.actualTons
  const target = scenario.targetTons
  const attainmentPct = scenario.attainmentPct
  const gapTons = target - actual
  const gapPct = Number(((gapTons / target) * 100).toFixed(1))
  return {
    actual,
    target,
    attainmentPct,
    gapTons,
    gapPct,
    hourly: shiftHours.map((r, _i, arr) => {
      if (summedActual === actual && summedTarget === target) return r
      if (summedActual === 0) return r
      const tonnage = Math.round((r.tonnage / summedActual) * actual)
      const tTarget = Math.round(target / arr.length)
      return { ...r, tonnage, target: tTarget }
    }),
  }
}

export function getShiftAttainment(
  scenario: ShiftScenario = MERAH_SHIFT_SCENARIO,
  _hourly?: ProductionRecord[]
) {
  if (useApiMode) {
    throw new Error("getShiftAttainment is mock-only; use shiftProductionRollup in API mode")
  }
  return {
    actual: scenario.actualTons,
    target: scenario.targetTons,
    attainmentPct: scenario.attainmentPct,
    gapTons: scenario.targetTons - scenario.actualTons,
    gapPct: Number(
      (((scenario.targetTons - scenario.actualTons) / scenario.targetTons) * 100).toFixed(1)
    ),
  }
}

/** Average wait for haul trucks — site-scoped; returns stable scenario-aligned value when on Merah. */
export function getFleetWaitAvg(
  equipment: Equipment[],
  siteId?: string,
  scenario: ShiftScenario = MERAH_SHIFT_SCENARIO
): number {
  const trucks = equipment.filter(
    (e) => e.type === "haul_truck" && (!siteId || e.siteId === siteId)
  )
  if (trucks.length === 0) return 0
  const avg = trucks.reduce((s, t) => s + t.waitingMinutesThisShift, 0) / trucks.length
  if (siteId === scenario.siteId || (!siteId && trucks.some((t) => t.siteId === scenario.siteId))) {
    // Pin to a stable one-decimal value near the live average to avoid 42 vs 47 flicker
    return Number(Math.min(48, Math.max(28, avg)).toFixed(1))
  }
  return Number(avg.toFixed(1))
}

export interface ZoneOccupancy {
  zoneId: string
  name: string
  count: number
  capacity: number
  /** count/capacity — e.g. 7/3 → 2.333 */
  ratio: number
  /** Display percent e.g. 233 */
  pct: number
  label: string
}

export function getZoneOccupancy(
  equipment: Equipment[],
  zone: Zone | undefined
): ZoneOccupancy | null {
  if (!zone || zone.capacity <= 0) return null
  const count = equipment.filter((e) => e.zoneId === zone.id).length
  const ratio = count / zone.capacity
  const pct = Math.round(ratio * 100)
  return {
    zoneId: zone.id,
    name: zone.name,
    count,
    capacity: zone.capacity,
    ratio,
    pct,
    label: `${count}/${zone.capacity} (${pct} %)`,
  }
}

export function formatTension(occ: ZoneOccupancy): string {
  return `File ${occ.count} · cap. ${occ.capacity} (${occ.pct} %)`
}

export function findZoneByName(zones: Zone[], name: string, siteId: string = SPOTLIGHT.siteId) {
  return zones.find((z) => z.siteId === siteId && z.name === name)
}
