import type {
  Alert,
  CycleStage,
  Equipment,
  EquipmentState,
  ProductionRecord,
  TimelineSegment,
  Zone,
} from "./types"
import { CYCLE_STAGE_ORDER } from "./types"
import type { MockWorld } from "./generator"

/** Stable spotlight entities for Merah El Ahrach morning shift. */
export const SPOTLIGHT = {
  siteId: "site-khouribga",
  shiftId: "shift-morning",
  truckStop: "TRK-012",
  truckNoComm: "TRK-004",
  excavatorMaint: "EXC-027",
  bancAName: "Banc de chargement A",
  bancBName: "Banc de chargement B",
} as const

export const SPOTLIGHT_CODES = new Set<string>([
  SPOTLIGHT.truckStop,
  SPOTLIGHT.truckNoComm,
  SPOTLIGHT.excavatorMaint,
])

export interface ShiftScenario {
  siteId: string
  siteName: string
  shiftId: string
  shiftLabel: string
  shiftStartHour: number
  shiftEndHour: number
  targetTons: number
  actualTons: number
  attainmentPct: number
  narrative: {
    headline: string
    body: string
    evidence: string[]
    next: string
    action: string
  }
  congestion: {
    zoneName: string
    afterHour: number
    afterMinute: number
    truckCount: number
  }
  optimisation: {
    fromZone: string
    toZone: string
    trucksToMove: number
  }
  spotlight: {
    stopTruck: string
    stopMinutes: number
    noCommTruck: string
    noCommMinutes: number
    maintExcavator: string
  }
}

export const MERAH_SHIFT_SCENARIO: ShiftScenario = {
  siteId: SPOTLIGHT.siteId,
  siteName: "Khouribga — Merah El Ahrach",
  shiftId: SPOTLIGHT.shiftId,
  shiftLabel: "Poste matin 06:00–14:00",
  shiftStartHour: 6,
  shiftEndHour: 14,
  targetTons: 8160,
  actualTons: 7231,
  attainmentPct: 88.6,
  narrative: {
    headline: "Production −11 % — Banc B saturé depuis 10:30",
    body: "Environ 7 camions attendent sur Banc B alors qu'EXC-027 est en maintenance. TRK-012 est en arrêt non défini (~23 min) et TRK-004 sans télémétrie (~5 min). Le cycle moyen remonte depuis 11:00.",
    evidence: [
      "Atteinte 7 231 / 8 160 t (88,6 %)",
      "Banc B ~7 camions en file depuis 10:30",
      "EXC-027 arrêt matériel — maintenance",
      "TRK-012 arrêt non défini ~23 min · TRK-004 aucune donnée ~5 min",
      "Cycle moyen en hausse après 11:00",
    ],
    next: "Sans rééquilibrage, l'écart objectif devrait se creuser encore d'ici 14:00.",
    action: "Rediriger 3–4 camions du Banc B vers le Banc A.",
  },
  congestion: {
    zoneName: SPOTLIGHT.bancBName,
    afterHour: 10,
    afterMinute: 30,
    truckCount: 7,
  },
  optimisation: {
    fromZone: SPOTLIGHT.bancBName,
    toZone: SPOTLIGHT.bancAName,
    trucksToMove: 4,
  },
  spotlight: {
    stopTruck: SPOTLIGHT.truckStop,
    stopMinutes: 23,
    noCommTruck: SPOTLIGHT.truckNoComm,
    noCommMinutes: 5,
    maintExcavator: SPOTLIGHT.excavatorMaint,
  },
}

function shiftStartMs(): number {
  const d = new Date()
  d.setHours(6, 0, 0, 0)
  return d.getTime()
}

function atToday(hour: number, minute = 0): number {
  const d = new Date()
  d.setHours(hour, minute, 0, 0)
  return d.getTime()
}

function findZone(zones: Zone[], siteId: string, name: string): Zone | undefined {
  return zones.find((z) => z.siteId === siteId && z.name === name)
}

function zoneCenter(zone: Zone) {
  const n = zone.points.length || 1
  return zone.points.reduce(
    (acc, p) => ({ x: acc.x + p.x / n, y: acc.y + p.y / n }),
    { x: 0, y: 0 }
  )
}

function stagesFor(
  current: number,
  minutes: number[],
  outliers: boolean[] = []
): CycleStage[] {
  return CYCLE_STAGE_ORDER.map((key, i) => {
    if (i > current) return { key, minutes: null, isCurrent: false, isOutlier: false }
    return {
      key,
      minutes: minutes[i] ?? 8,
      isCurrent: i === current,
      isOutlier: outliers[i] ?? false,
    }
  })
}

function ensureSpotlightCodes(equipment: Equipment[], siteId: string): Equipment[] {
  const siteEq = equipment.filter((e) => e.siteId === siteId)
  const trucks = siteEq.filter((e) => e.type === "haul_truck")
  const excavators = siteEq.filter((e) => e.type === "excavator")
  const byId = new Map(equipment.map((e) => [e.id, e]))

  const forceCode = (eq: Equipment | undefined, code: string) => {
    if (!eq || eq.code === code) return
    // Swap codes if another unit already holds the spotlight code
    const holder = equipment.find((e) => e.code === code)
    if (holder) {
      byId.set(holder.id, { ...holder, code: eq.code })
    }
    byId.set(eq.id, { ...eq, code })
  }

  forceCode(trucks[3], SPOTLIGHT.truckNoComm)
  forceCode(trucks[11], SPOTLIGHT.truckStop)
  forceCode(excavators[0], SPOTLIGHT.excavatorMaint)

  return equipment.map((e) => byId.get(e.id) ?? e)
}

function patchEquipment(
  equipment: Equipment[],
  zones: Zone[],
  scenario: ShiftScenario
): Equipment[] {
  const siteId = scenario.siteId
  const bancA = findZone(zones, siteId, scenario.optimisation.toZone)
  const bancB = findZone(zones, siteId, scenario.optimisation.fromZone)
  const atelier = zones.find((z) => z.siteId === siteId && z.type === "atelier")
  const parking = zones.find((z) => z.siteId === siteId && z.type === "parking")

  const siteTrucks = equipment.filter(
    (e) => e.siteId === siteId && e.type === "haul_truck"
  )
  const congestIds = new Set(
    siteTrucks
      .filter(
        (t) =>
          t.code !== scenario.spotlight.stopTruck &&
          t.code !== scenario.spotlight.noCommTruck
      )
      .slice(0, scenario.congestion.truckCount)
      .map((t) => t.id)
  )

  // Keep non-queue trucks off Banc B so occupancy stays exactly 7/3
  const reliefZone = bancA ?? parking

  return equipment.map((eq) => {
    if (eq.siteId !== siteId) return eq

    if (eq.code === scenario.spotlight.maintExcavator) {
      const z = atelier ?? bancB
      const center = z ? zoneCenter(z) : (eq.position ?? { x: 0, y: 0 })
      return {
        ...eq,
        state: "arret_materiel" as EquipmentState,
        engineOn: false,
        speedKmh: 0,
        zoneId: z?.id ?? eq.zoneId,
        position: { x: center.x + 8, y: center.y - 6 },
        waitingMinutesThisShift: 0,
        idleMinutesThisShift: 95,
        lastUpdate: Date.now() - 2 * 60_000,
        healthScore: 54,
        cycleActuel: stagesFor(0, [0], [false]),
      }
    }

    if (eq.code === scenario.spotlight.stopTruck) {
      const z = parking ?? bancB
      const center = z ? zoneCenter(z) : (eq.position ?? { x: 0, y: 0 })
      return {
        ...eq,
        state: "arret_indetermine" as EquipmentState,
        engineOn: true,
        speedKmh: 0,
        zoneId: z?.id ?? eq.zoneId,
        position: { x: center.x - 12, y: center.y + 10 },
        waitingMinutesThisShift: scenario.spotlight.stopMinutes,
        idleMinutesThisShift: scenario.spotlight.stopMinutes,
        lastUpdate: Date.now() - scenario.spotlight.stopMinutes * 60_000,
        cycleActuel: stagesFor(1, [9, scenario.spotlight.stopMinutes], [false, true]),
        cycleDureeMoyenneMin: 42,
      }
    }

    if (eq.code === scenario.spotlight.noCommTruck) {
      const center = bancA ? zoneCenter(bancA) : (eq.position ?? { x: 0, y: 0 })
      return {
        ...eq,
        state: "aucune_donnee" as EquipmentState,
        engineOn: true,
        speedKmh: 0,
        zoneId: bancA?.id ?? eq.zoneId,
        position: { x: center.x + 20, y: center.y + 14 },
        waitingMinutesThisShift: 8,
        idleMinutesThisShift: scenario.spotlight.noCommMinutes,
        lastUpdate: Date.now() - scenario.spotlight.noCommMinutes * 60_000,
        cycleActuel: stagesFor(2, [7, 4, 5], [false, false, false]),
        cycleDureeMoyenneMin: 44,
      }
    }

    if (congestIds.has(eq.id) && bancB) {
      const center = zoneCenter(bancB)
      const idx = [...congestIds].indexOf(eq.id)
      return {
        ...eq,
        state: (idx % 2 === 0 ? "attente_charge" : "mouvement_vide") as EquipmentState,
        engineOn: true,
        speedKmh: idx % 2 === 0 ? 0 : 12,
        zoneId: bancB.id,
        destinationZoneId: bancB.id,
        position: {
          x: center.x + (idx - 3) * 18,
          y: center.y + (idx % 3) * 14 - 10,
        },
        waitingMinutesThisShift: 22 + idx * 2,
        lastUpdate: Date.now() - idx * 20_000,
        cycleActuel: stagesFor(1, [8, 14 + idx * 2], [false, true]),
        cycleDureeMoyenneMin: 48,
      }
    }

    // Explicitly clear Banc B for everyone else
    if (
      eq.type === "haul_truck" &&
      bancB &&
      eq.zoneId === bancB.id &&
      !congestIds.has(eq.id)
    ) {
      const z = reliefZone
      const center = z ? zoneCenter(z) : (eq.position ?? { x: 0, y: 0 })
      return {
        ...eq,
        zoneId: z?.id ?? eq.zoneId,
        position: { x: center.x + Math.random() * 40 - 20, y: center.y + Math.random() * 30 - 15 },
        waitingMinutesThisShift: Math.min(eq.waitingMinutesThisShift, 16),
        cycleDureeMoyenneMin: Math.max(eq.cycleDureeMoyenneMin ?? 0, 40),
      }
    }

    if (eq.type === "haul_truck") {
      return {
        ...eq,
        cycleDureeMoyenneMin: Math.max(eq.cycleDureeMoyenneMin ?? 0, 40),
        waitingMinutesThisShift: Math.min(Math.max(eq.waitingMinutesThisShift, 6), 28),
      }
    }

    return eq
  })
}

function buildScenarioAlerts(
  equipment: Equipment[],
  zones: Zone[],
  existing: Alert[],
  scenario: ShiftScenario
): Alert[] {
  const now = Date.now()
  const siteId = scenario.siteId
  const bancB = findZone(zones, siteId, scenario.congestion.zoneName)
  const stopEq = equipment.find((e) => e.code === scenario.spotlight.stopTruck)
  const noCommEq = equipment.find((e) => e.code === scenario.spotlight.noCommTruck)
  const maintEq = equipment.find((e) => e.code === scenario.spotlight.maintExcavator)

  const scenarioAlerts: Alert[] = [
    {
      id: "EVT-SCENARIO-001",
      severity: "critical",
      status: "new",
      title: "Arrêt non défini — cause inconnue",
      description: `${scenario.spotlight.stopTruck} arrêté sans cause déclarée depuis ~${scenario.spotlight.stopMinutes} min.`,
      equipmentId: stopEq?.id ?? null,
      zoneId: stopEq?.zoneId ?? null,
      location: stopEq ? `Position ${stopEq.code}` : "Parking engins",
      category: "Arrêt",
      createdAt: now - scenario.spotlight.stopMinutes * 60_000,
      updatedAt: now - 2 * 60_000,
      assignedTo: null,
      resolution: null,
    },
    {
      id: "EVT-SCENARIO-002",
      severity: "critical",
      status: "investigating",
      title: "Perte de communication",
      description: `${scenario.spotlight.noCommTruck} — aucune télémétrie reçue depuis ~${scenario.spotlight.noCommMinutes} min.`,
      equipmentId: noCommEq?.id ?? null,
      zoneId: noCommEq?.zoneId ?? null,
      location: findZone(zones, siteId, scenario.optimisation.toZone)?.name ?? "Banc A",
      category: "Communication",
      createdAt: now - scenario.spotlight.noCommMinutes * 60_000,
      updatedAt: now - 60_000,
      assignedTo: "Régulateur de poste",
      resolution: null,
    },
    {
      id: "EVT-SCENARIO-003",
      severity: "warning",
      status: "assigned",
      title: "Maintenance pelle — EXC-027",
      description: `${scenario.spotlight.maintExcavator} en arrêt matériel — intervention maintenance en cours.`,
      equipmentId: maintEq?.id ?? null,
      zoneId: maintEq?.zoneId ?? null,
      location: "Atelier maintenance",
      category: "Maintenance",
      createdAt: atToday(8, 15),
      updatedAt: atToday(9, 40),
      assignedTo: "Atelier MEA",
      resolution: null,
    },
    {
      id: "EVT-SCENARIO-004",
      severity: "warning",
      status: "acknowledged",
      title: "Congestion Banc B",
      description: `File anormale (~${scenario.congestion.truckCount} camions) sur ${scenario.congestion.zoneName} depuis 10:30.`,
      equipmentId: null,
      zoneId: bancB?.id ?? null,
      location: scenario.congestion.zoneName,
      category: "Congestion",
      createdAt: atToday(10, 32),
      updatedAt: atToday(10, 45),
      assignedTo: null,
      resolution: null,
    },
    {
      id: "EVT-SCENARIO-005",
      severity: "warning",
      status: "new",
      title: "Cycle trop long — dégradation post-11:00",
      description: "Durée de cycle moyenne en hausse après 11:00 — attentes de chargement Banc B.",
      equipmentId: stopEq?.id ?? null,
      zoneId: bancB?.id ?? null,
      location: scenario.congestion.zoneName,
      category: "Cycle",
      createdAt: atToday(11, 10),
      updatedAt: atToday(11, 10),
      assignedTo: null,
      resolution: null,
    },
  ]

  const spotlightIds = new Set(
    [stopEq?.id, noCommEq?.id, maintEq?.id].filter(Boolean) as string[]
  )
  const retained = existing.filter((a) => {
    if (a.equipmentId && spotlightIds.has(a.equipmentId)) return false
    if (a.zoneId && bancB && a.zoneId === bancB.id && a.category === "Congestion") return false
    return true
  })

  return [...scenarioAlerts, ...retained].sort((a, b) => b.createdAt - a.createdAt)
}

function patchTimeline(
  segments: TimelineSegment[],
  equipment: Equipment[],
  zones: Zone[],
  scenario: ShiftScenario
): TimelineSegment[] {
  const start = shiftStartMs()
  const now = Date.now()
  const bancB = findZone(zones, scenario.siteId, scenario.congestion.zoneName)
  const bancA = findZone(zones, scenario.siteId, scenario.optimisation.toZone)
  const stopEq = equipment.find((e) => e.code === scenario.spotlight.stopTruck)
  const noCommEq = equipment.find((e) => e.code === scenario.spotlight.noCommTruck)
  const maintEq = equipment.find((e) => e.code === scenario.spotlight.maintExcavator)

  const withoutSpotlight = segments.filter(
    (s) =>
      s.equipmentId !== stopEq?.id &&
      s.equipmentId !== noCommEq?.id &&
      s.equipmentId !== maintEq?.id
  )

  const crafted: TimelineSegment[] = []

  if (stopEq) {
    const stopStart = now - scenario.spotlight.stopMinutes * 60_000
    crafted.push(
      {
        id: `${stopEq.id}-scen-0`,
        equipmentId: stopEq.id,
        state: "mouvement_vide",
        start,
        end: atToday(9, 40),
        zoneName: bancA?.name ?? null,
      },
      {
        id: `${stopEq.id}-scen-1`,
        equipmentId: stopEq.id,
        state: "attente_charge",
        start: atToday(9, 40),
        end: atToday(10, 5),
        zoneName: bancB?.name ?? null,
      },
      {
        id: `${stopEq.id}-scen-2`,
        equipmentId: stopEq.id,
        state: "chargement",
        start: atToday(10, 5),
        end: atToday(10, 12),
        zoneName: bancB?.name ?? null,
      },
      {
        id: `${stopEq.id}-scen-3`,
        equipmentId: stopEq.id,
        state: "mouvement_charge",
        start: atToday(10, 12),
        end: atToday(10, 45),
        zoneName: null,
      },
      {
        id: `${stopEq.id}-scen-3b`,
        equipmentId: stopEq.id,
        state: "dechargement",
        start: atToday(10, 45),
        end: atToday(10, 53),
        zoneName: "Concasseur primaire",
      },
      {
        id: `${stopEq.id}-scen-3c`,
        equipmentId: stopEq.id,
        state: "mouvement_vide",
        start: atToday(10, 53),
        end: stopStart,
        zoneName: null,
      },
      {
        id: `${stopEq.id}-scen-4`,
        equipmentId: stopEq.id,
        state: "arret_indetermine",
        start: stopStart,
        end: now,
        zoneName: "Parking engins",
      }
    )
  }

  if (noCommEq) {
    const lostAt = now - scenario.spotlight.noCommMinutes * 60_000
    crafted.push(
      {
        id: `${noCommEq.id}-scen-0`,
        equipmentId: noCommEq.id,
        state: "mouvement_charge",
        start,
        end: lostAt - 20 * 60_000,
        zoneName: null,
      },
      {
        id: `${noCommEq.id}-scen-1`,
        equipmentId: noCommEq.id,
        state: "attente_dechargement",
        start: lostAt - 20 * 60_000,
        end: lostAt,
        zoneName: "Concasseur primaire",
      },
      {
        id: `${noCommEq.id}-scen-2`,
        equipmentId: noCommEq.id,
        state: "aucune_donnee",
        start: lostAt,
        end: now,
        zoneName: bancA?.name ?? null,
      }
    )
  }

  if (maintEq) {
    crafted.push(
      {
        id: `${maintEq.id}-scen-0`,
        equipmentId: maintEq.id,
        state: "chargement",
        start,
        end: atToday(8, 10),
        zoneName: bancB?.name ?? null,
      },
      {
        id: `${maintEq.id}-scen-1`,
        equipmentId: maintEq.id,
        state: "arret_materiel",
        start: atToday(8, 10),
        end: now,
        zoneName: "Atelier maintenance",
      }
    )
  }

  const congestTrucks = equipment.filter(
    (e) =>
      e.siteId === scenario.siteId &&
      e.type === "haul_truck" &&
      e.zoneId === bancB?.id &&
      !SPOTLIGHT_CODES.has(e.code)
  )
  const after11 = atToday(11, 0)
  congestTrucks.slice(0, 5).forEach((truck, i) => {
    withoutSpotlight.push({
      id: `${truck.id}-scen-wait-11`,
      equipmentId: truck.id,
      state: "attente_charge",
      start: after11,
      end: Math.min(now, after11 + (18 + i * 4) * 60_000),
      zoneName: bancB?.name ?? null,
    })
  })

  return [...withoutSpotlight, ...crafted]
}

function buildHourlyProduction(scenario: ShiftScenario): ProductionRecord[] {
  const hourlyTargets = 1020
  const factors: Record<number, number> = {
    6: 0.92,
    7: 0.98,
    8: 1.02,
    9: 0.96,
    10: 0.88,
    11: 0.78,
    12: 0.8,
    13: 0.82,
  }
  const hours = [6, 7, 8, 9, 10, 11, 12, 13]
  let raw = hours.map((h) => Math.round(hourlyTargets * (factors[h] ?? 0.9)))
  const sum = raw.reduce((a, b) => a + b, 0)
  raw = raw.map((v) => Math.round((v * scenario.actualTons) / sum))
  const diff = scenario.actualTons - raw.reduce((a, b) => a + b, 0)
  raw[raw.length - 1] += diff

  const hourly: ProductionRecord[] = hours.map((h, i) => ({
    label: `${String(h).padStart(2, "0")}:00`,
    target: hourlyTargets,
    tonnage: raw[i],
  }))

  // Morning shift only — do not append zero afternoon hours (misleading on charts)
  return hourly
}

/**
 * Patches a generated mock world so Merah El Ahrach morning shift tells one coherent story.
 * Spotlight codes TRK-012, TRK-004, EXC-027 and Banc A/B remain stable.
 */
export function applyCoherentScenario(
  world: MockWorld,
  scenario: ShiftScenario = MERAH_SHIFT_SCENARIO
): MockWorld {
  const zones = world.zones.map((z) => {
    if (z.siteId !== scenario.siteId) return z
    if (z.type === "chargement" && z.name.includes("A")) {
      return { ...z, name: SPOTLIGHT.bancAName, capacity: 4 }
    }
    if (z.type === "chargement" && z.name.includes("B")) {
      return { ...z, name: SPOTLIGHT.bancBName, capacity: 3 }
    }
    return z
  })

  let equipment = ensureSpotlightCodes(world.equipment, scenario.siteId)
  equipment = patchEquipment(equipment, zones, scenario)

  const alerts = buildScenarioAlerts(equipment, zones, world.alerts, scenario)
  const timelineSegments = patchTimeline(
    world.timelineSegments,
    equipment,
    zones,
    scenario
  )

  const hourly = buildHourlyProduction(scenario)
  const productionByShift = {
    ...world.productionByShift,
    hourly,
    shiftly: [
      {
        label: "Poste matin",
        target: scenario.targetTons,
        tonnage: scenario.actualTons,
      },
      ...(world.productionByShift.shiftly?.slice(1) ?? []),
    ],
  }

  const downtimeReasons = [
    { reason: "Attente de chargement", hours: 28 },
    { reason: "Congestion piste", hours: 14 },
    { reason: "Maintenance programmée", hours: 11 },
    { reason: "Panne non planifiée", hours: 6 },
    { reason: "Arrêt non défini", hours: 5 },
    { reason: "Perte de communication", hours: 2 },
    { reason: "Relève de poste", hours: 4 },
    { reason: "Ravitaillement", hours: 3 },
  ]

  return {
    ...world,
    zones,
    equipment,
    alerts,
    timelineSegments,
    productionByShift,
    downtimeReasons,
  }
}
