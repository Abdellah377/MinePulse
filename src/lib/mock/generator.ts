import type {
  Alert,
  AlertSeverity,
  CycleStage,
  CycleStageKey,
  CycleTimeSample,
  DowntimeReason,
  Equipment,
  EquipmentState,
  EquipmentType,
  Operator,
  ProductionRecord,
  RoutePath,
  Shift,
  Site,
  TimelineSegment,
  Vec2,
  Zone,
  ZoneType,
} from "./types"
import { CYCLE_STAGE_ORDER, ZONE_TYPE_COLOR } from "./types"
import { applyCoherentScenario } from "./scenario"
import { buildDemoRoutes } from "@/lib/map/demoLayout"

/** Deterministic PRNG so the initial mock world is stable across reloads. */
function mulberry32(seed: number) {
  let a = seed
  return function () {
    a |= 0
    a = (a + 0x6d2b79f5) | 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

let rng = mulberry32(20260129)

function rand(min = 0, max = 1) {
  return min + rng() * (max - min)
}

function randInt(min: number, max: number) {
  return Math.floor(rand(min, max + 1))
}

function pick<T>(arr: readonly T[]): T {
  return arr[randInt(0, arr.length - 1)]
}

function uid(prefix: string, n: number) {
  return `${prefix}-${String(n).padStart(3, "0")}`
}

export const SITES: Site[] = [
  {
    id: "site-khouribga",
    name: "Khouribga — Merah El Ahrach",
    region: "Bassin de Khouribga",
    pits: [
      { id: "pit-mea-1", name: "Panneau 1" },
      { id: "pit-mea-2", name: "Panneau 2" },
    ],
  },
  {
    id: "site-benguerir",
    name: "Benguerir — Plateau Sud",
    region: "Bassin de Gantour",
    pits: [{ id: "pit-bg-1", name: "Bloc Sud" }],
  },
  {
    id: "site-youssoufia",
    name: "Youssoufia — Sud",
    region: "Bassin de Gantour",
    pits: [{ id: "pit-ys-1", name: "Bloc A" }],
  },
]

export const SHIFTS: Shift[] = [
  { id: "shift-morning", name: "Poste matin", startHour: 6, endHour: 14 },
  { id: "shift-afternoon", name: "Poste après-midi", startHour: 14, endHour: 22 },
  { id: "shift-night", name: "Poste nuit", startHour: 22, endHour: 6 },
]

const TRUCK_MODELS = ["CAT 793F", "Komatsu 830E-5", "Liebherr T 284", "CAT 789D"]
const EXCAVATOR_MODELS = ["Komatsu PC3000", "CAT 6015B", "Liebherr R 9400"]
const LOADER_MODELS = ["CAT 992K", "Komatsu WA900-8"]
const DOZER_MODELS = ["CAT D11T", "Komatsu D375A"]
const DRILL_MODELS = ["Atlas Copco Pit Viper 271", "Sandvik DR416i"]
const GRADER_MODELS = ["CAT 24M", "Komatsu GD825A"]

const ASSIGNEE_ROLES = [
  "Régulateur de poste",
  "Chef de poste",
  "Atelier",
  "Dispatch",
  "Maintenance",
]

function vec(x: number, y: number): Vec2 {
  return { x, y }
}

/** A loosely rectangular polygon (not a perfect box) so zones read as hand-surveyed areas. */
function quadZone(cx: number, cy: number, w: number, h: number): Vec2[] {
  const jitter = () => rand(-0.06, 0.06)
  return [
    vec(cx - w / 2 + w * jitter(), cy - h / 2 + h * jitter()),
    vec(cx + w / 2 + w * jitter(), cy - h / 2 + h * jitter()),
    vec(cx + w / 2 + w * jitter(), cy + h / 2 + h * jitter()),
    vec(cx - w / 2 + w * jitter(), cy + h / 2 + h * jitter()),
  ]
}

function zoneCenter(points: Vec2[]): Vec2 {
  const n = points.length
  return points.reduce(
    (acc, p) => ({ x: acc.x + p.x / n, y: acc.y + p.y / n }),
    { x: 0, y: 0 }
  )
}

const ZONE_DESCRIPTIONS: Record<ZoneType, string> = {
  chargement: "Banc de chargement — pelle assignée, file d'attente camions.",
  dechargement: "Zone de mise à terril / stock stériles.",
  concasseur: "Concasseur primaire. Destination prioritaire du minerai haute teneur.",
  fuel: "Station de ravitaillement gasoil. Accès limité pendant le ravitaillement.",
  atelier: "Atelier de maintenance mécanique. File d'attente hors production.",
  parking: "Parking engins — attente de poste et voie de report vers le concasseur.",
  restreinte: "Aire de préparation de tir. Accès interdit pendant les opérations de minage.",
}

interface SiteBundle {
  zones: Zone[]
  routes: RoutePath[]
  equipment: Equipment[]
  operators: Operator[]
}

function buildZones(siteId: string): Zone[] {
  const specs: { name: string; type: ZoneType; cx: number; cy: number; w: number; h: number; capacity: number }[] = [
    { name: "Banc de chargement A", type: "chargement", cx: 160, cy: 150, w: 130, h: 100, capacity: 3 },
    { name: "Banc de chargement B", type: "chargement", cx: 180, cy: 400, w: 130, h: 100, capacity: 3 },
    { name: "Concasseur primaire", type: "concasseur", cx: 760, cy: 130, w: 110, h: 90, capacity: 2 },
    { name: "Terril stériles 2", type: "dechargement", cx: 820, cy: 420, w: 130, h: 100, capacity: 4 },
    { name: "Atelier maintenance", type: "atelier", cx: 500, cy: 520, w: 100, h: 80, capacity: 6 },
    { name: "Station fuel", type: "fuel", cx: 500, cy: 60, w: 70, h: 55, capacity: 2 },
    { name: "Parking engins", type: "parking", cx: 300, cy: 540, w: 90, h: 60, capacity: 8 },
    { name: "Aire de tir", type: "restreinte", cx: 920, cy: 260, w: 80, h: 140, capacity: 0 },
  ]
  return specs.map((s, i) => ({
    id: `${siteId}-zone-${i}`,
    name: s.name,
    type: s.type,
    points: quadZone(s.cx, s.cy, s.w, s.h),
    color: ZONE_TYPE_COLOR[s.type],
    description: ZONE_DESCRIPTIONS[s.type],
    capacity: s.capacity,
    siteId,
  }))
}

function buildRoutes(siteId: string, zones: Zone[]): RoutePath[] {
  return buildDemoRoutes(siteId, zones)
}

const STATE_WEIGHTS: [EquipmentState, number][] = [
  ["mouvement_charge", 0.18],
  ["mouvement_vide", 0.18],
  ["attente_charge", 0.1],
  ["chargement", 0.08],
  ["attente_dechargement", 0.1],
  ["dechargement", 0.08],
  ["arret_exploitation", 0.08],
  ["arret_materiel", 0.06],
  ["arret_exterieur", 0.04],
  ["arret_indetermine", 0.03],
  ["eteint", 0.05],
  ["aucune_donnee", 0.01],
  ["indetermine", 0.01],
]

function weightedState(): EquipmentState {
  const r = rng()
  let acc = 0
  for (const [state, w] of STATE_WEIGHTS) {
    acc += w
    if (r <= acc) return state
  }
  return "indetermine"
}

const CYCLE_STAGE_RANGE: Record<CycleStageKey, [number, number]> = {
  vide: [6, 22],
  attente_charge: [0, 12],
  chargement: [3, 9],
  charge: [6, 20],
  attente_dechargement: [0, 10],
  dechargement: [3, 9],
}

function buildCycleActuel(): { stages: CycleStage[]; dureeMoyenneMin: number } {
  const currentIndex = randInt(0, CYCLE_STAGE_ORDER.length - 1)
  const stages: CycleStage[] = CYCLE_STAGE_ORDER.map((key, i) => {
    if (i > currentIndex) return { key, minutes: null, isCurrent: false, isOutlier: false }
    const [min, max] = CYCLE_STAGE_RANGE[key]
    const isCurrent = i === currentIndex
    const stretch = isCurrent && rng() < 0.3 ? rand(1.6, 3.2) : 1
    const minutes = Math.round(rand(min, max) * stretch)
    const isOutlier = minutes > max * 1.6
    return { key, minutes, isCurrent, isOutlier }
  })
  const dureeMoyenneMin = Math.round(
    CYCLE_STAGE_ORDER.reduce((sum, key) => {
      const [min, max] = CYCLE_STAGE_RANGE[key]
      return sum + (min + max) / 2
    }, 0)
  )
  return { stages, dureeMoyenneMin }
}

function buildEquipmentAndOperators(
  siteId: string,
  zones: Zone[],
  counter: { n: number; op: number }
): { equipment: Equipment[]; operators: Operator[] } {
  const equipment: Equipment[] = []
  const operators: Operator[] = []
  const loadZones = zones.filter((z) => z.type === "chargement")
  const dumpZones = zones.filter((z) => z.type === "dechargement" || z.type === "concasseur")

  const spawn = (
    type: EquipmentType,
    models: string[],
    count: number,
    capacityTons: number
  ) => {
    for (let i = 0; i < count; i++) {
      counter.n += 1
      counter.op += 1
      const state = weightedState()
      const anchor = pick(zones)
      const anchorCenter = zoneCenter(anchor.points)
      const opId = uid("OP", counter.op)
      const eqId = uid(
        type === "haul_truck"
          ? "TRK"
          : type === "excavator"
            ? "EXC"
            : type === "loader"
              ? "LDR"
              : type === "dozer"
                ? "DOZ"
                : type === "drill"
                  ? "DRL"
                  : "GRD",
        counter.n
      )
      const isDown =
        state === "arret_exploitation" ||
        state === "arret_materiel" ||
        state === "arret_exterieur" ||
        state === "arret_indetermine" ||
        state === "eteint"
      const { stages, dureeMoyenneMin } = buildCycleActuel()
      const eq: Equipment = {
        id: eqId,
        code: eqId,
        type,
        model: pick(models),
        state,
        position: {
          x: anchorCenter.x + rand(-70, 70),
          y: anchorCenter.y + rand(-70, 70),
        },
        heading: rand(0, 360),
        speedKmh:
          state === "mouvement_charge"
            ? rand(18, 34)
            : state === "mouvement_vide"
              ? rand(24, 42)
              : 0,
        fuelPct: rand(28, 98),
        gasoilLph: rand(28, 68),
        tdPct: rand(68, 98),
        tuPct: rand(45, 92),
        engineOn: !isDown,
        operatorId: isDown ? null : opId,
        zoneId: pick(zones).id,
        destinationZoneId:
          state === "mouvement_charge" ? pick(dumpZones).id : pick(loadZones).id,
        payloadTons: state === "mouvement_charge" ? capacityTons * rand(0.85, 1.02) : 0,
        capacityTons,
        odometerKm: rand(12000, 98000),
        engineHours: rand(2000, 26000),
        tripsThisShift: randInt(2, 18),
        waitingMinutesThisShift: randInt(0, 95),
        idleMinutesThisShift: randInt(0, 60),
        lastUpdate: Date.now() - randInt(0, 8000),
        siteId,
        healthScore: rand(62, 99),
        cycleActuel: stages,
        cycleDureeMoyenneMin: dureeMoyenneMin,
      }
      equipment.push(eq)

      if (eq.operatorId) {
        const badge = `OP-${String(1000 + counter.op).slice(-3)}`
        operators.push({
          id: eq.operatorId,
          name: `Conducteur ${badge}`,
          badgeId: badge,
          certLevel: pick(["Trainee", "Certified", "Certified", "Senior"] as const),
          shiftId: pick(SHIFTS).id,
          assignedEquipmentId: eq.id,
          cyclesThisShift: eq.tripsThisShift,
          idleMinutes: eq.idleMinutesThisShift,
          performanceScore: rand(58, 98),
          status: pick(["active", "active", "active", "break"] as const),
          siteId,
        })
      }
    }
  }

  spawn("haul_truck", TRUCK_MODELS, 26, 220)
  spawn("excavator", EXCAVATOR_MODELS, 6, 0)
  spawn("loader", LOADER_MODELS, 4, 0)
  spawn("dozer", DOZER_MODELS, 3, 0)
  spawn("drill", DRILL_MODELS, 2, 0)
  spawn("grader", GRADER_MODELS, 2, 0)

  return { equipment, operators }
}

function buildSite(siteId: string, counter: { n: number; op: number }): SiteBundle {
  const zones = buildZones(siteId)
  const routes = buildRoutes(siteId, zones)
  const { equipment, operators } = buildEquipmentAndOperators(siteId, zones, counter)
  return { zones, routes, equipment, operators }
}

export interface MockWorld {
  zones: Zone[]
  routes: RoutePath[]
  equipment: Equipment[]
  operators: Operator[]
  alerts: Alert[]
  timelineSegments: TimelineSegment[]
  productionByShift: Record<string, ProductionRecord[]>
  cycleTimeSamples: CycleTimeSample[]
  downtimeReasons: DowntimeReason[]
}

const ALERT_TEMPLATES: {
  severity: AlertSeverity
  category: string
  title: string
  description: string
}[] = [
  {
    severity: "critical",
    category: "Arrêt",
    title: "Arrêt critique équipement",
    description: "arrêt matériel signalé — intervention requise sur site.",
  },
  {
    severity: "critical",
    category: "Communication",
    title: "Perte de communication",
    description: "aucune télémétrie reçue depuis plus de 5 minutes.",
  },
  {
    severity: "warning",
    category: "Gasoil",
    title: "Anomalie gasoil",
    description: "consommation anormale détectée — vérifier une fuite éventuelle.",
  },
  {
    severity: "warning",
    category: "Cycle",
    title: "Cycle trop long",
    description: "durée de cycle 22% au-dessus de la moyenne du poste.",
  },
  {
    severity: "warning",
    category: "Attente",
    title: "Attente trop longue",
    description: "attente supérieure au seuil (plus de 15 minutes).",
  },
  {
    severity: "warning",
    category: "Congestion",
    title: "Congestion de route",
    description: "file d'attente anormale détectée sur la zone.",
  },
  {
    severity: "info",
    category: "Maintenance",
    title: "Problème mécanique",
    description: "anomalie mineure détectée — entretien à prévoir.",
  },
  {
    severity: "info",
    category: "Poste",
    title: "Fin de poste imminente",
    description: "fin de poste opérateur dans 30 minutes — prévoir la passation.",
  },
]

const RESOLUTION_TEMPLATES = [
  "Camion redirigé vers un autre banc de chargement.",
  "Intervention mécanique effectuée, engin remis en service.",
  "Ravitaillement effectué, anomalie confirmée sans gravité.",
  "Régulation manuelle appliquée, file résorbée.",
  "Faux positif — équipement de nouveau opérationnel.",
]

function buildAlerts(equipment: Equipment[], zones: Zone[]): Alert[] {
  const alerts: Alert[] = []
  const now = Date.now()
  const sample = [...equipment].sort(() => rng() - 0.5).slice(0, 18)
  sample.forEach((eq, i) => {
    const template = pick(ALERT_TEMPLATES)
    const createdAt = now - randInt(1, 240) * 60_000
    const status = pick([
      "new",
      "new",
      "acknowledged",
      "investigating",
      "assigned",
      "resolved",
    ] as const)
    const siteZones = zones.filter((z) => z.siteId === eq.siteId)
    const zone = rng() < 0.6 ? pick(siteZones) : null
    alerts.push({
      id: uid("EVT", i + 1),
      severity: template.severity,
      status,
      title: template.title,
      description: `${eq.code} ${template.description}`,
      equipmentId: eq.id,
      zoneId: zone?.id ?? null,
      location: zone ? zone.name : `Position ${eq.code}`,
      category: template.category,
      createdAt,
      updatedAt: status === "new" ? createdAt : createdAt + randInt(1, 40) * 60_000,
      assignedTo:
        status === "assigned" || status === "resolved" || status === "investigating"
          ? pick(ASSIGNEE_ROLES)
          : null,
      resolution: status === "resolved" ? pick(RESOLUTION_TEMPLATES) : null,
    })
  })
  return alerts.sort((a, b) => b.createdAt - a.createdAt)
}

function buildTimelineSegments(equipment: Equipment[], zones: Zone[]): TimelineSegment[] {
  const segments: TimelineSegment[] = []
  const shiftStart = new Date()
  shiftStart.setHours(6, 0, 0, 0)
  const shiftStartMs = shiftStart.getTime()
  const now = Date.now()

  equipment.forEach((eq) => {
    let cursor = shiftStartMs
    let idx = 0
    while (cursor < now) {
      const state = weightedState()
      const durationMin =
        state === "attente_charge" || state === "attente_dechargement"
          ? randInt(4, 22)
          : state === "chargement" || state === "dechargement"
            ? randInt(3, 8)
            : state.startsWith("arret")
              ? randInt(30, 90)
              : randInt(6, 28)
      const end = Math.min(cursor + durationMin * 60_000, now)
      segments.push({
        id: `${eq.id}-seg-${idx}`,
        equipmentId: eq.id,
        state,
        start: cursor,
        end,
        zoneName:
          state === "chargement" || state === "attente_charge" || state === "attente_dechargement"
            ? pick(zones).name
            : null,
      })
      cursor = end
      idx += 1
    }
  })
  return segments
}

function buildProduction(): Record<string, ProductionRecord[]> {
  const hourly: ProductionRecord[] = []
  for (let h = 6; h <= 22; h++) {
    const target = 480
    hourly.push({
      label: `${String(h).padStart(2, "0")}:00`,
      target,
      tonnage: Math.round(target * rand(0.72, 1.12)),
    })
  }
  const daily: ProductionRecord[] = Array.from({ length: 14 }).map((_, i) => {
    const target = 9800
    return {
      label: `J-${14 - i}`,
      target,
      tonnage: Math.round(target * rand(0.8, 1.14)),
    }
  })
  const shiftly: ProductionRecord[] = SHIFTS.map((s) => ({
    label: s.name,
    target: 3300,
    tonnage: Math.round(3300 * rand(0.78, 1.1)),
  }))
  return { hourly, daily, shiftly }
}

function buildCycleTimeSamples(): CycleTimeSample[] {
  const types: EquipmentType[] = ["haul_truck", "excavator", "loader"]
  const buckets = ["0-10", "10-20", "20-30", "30-40", "40-50", "50-60+"]
  const samples: CycleTimeSample[] = []
  types.forEach((t) => {
    buckets.forEach((b) => {
      samples.push({ equipmentType: t, bucket: b, minutes: randInt(2, 60) })
    })
  })
  return samples
}

function buildDowntimeReasons(): DowntimeReason[] {
  return [
    { reason: "Attente de chargement", hours: rand(18, 42) },
    { reason: "Maintenance programmée", hours: rand(10, 28) },
    { reason: "Panne non planifiée", hours: rand(4, 18) },
    { reason: "Relève de poste", hours: rand(6, 14) },
    { reason: "Congestion piste", hours: rand(5, 16) },
    { reason: "Ravitaillement", hours: rand(3, 9) },
  ]
}

export function generateMockWorld(): MockWorld {
  rng = mulberry32(20260129)
  const counter = { n: 0, op: 0 }
  const bundles = SITES.map((s) => buildSite(s.id, counter))

  const zones = bundles.flatMap((b) => b.zones)
  const routes = bundles.flatMap((b) => b.routes)
  const equipment = bundles.flatMap((b) => b.equipment)
  const operators = bundles.flatMap((b) => b.operators)

  return applyCoherentScenario({
    zones,
    routes,
    equipment,
    operators,
    alerts: buildAlerts(equipment, zones),
    timelineSegments: buildTimelineSegments(equipment, zones),
    productionByShift: buildProduction(),
    cycleTimeSamples: buildCycleTimeSamples(),
    downtimeReasons: buildDowntimeReasons(),
  })
}
