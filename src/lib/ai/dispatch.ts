import type { AiInsight } from "@/components/ai/AiSlot"
import type { Equipment, ProductionRecord, Zone } from "@/lib/mock/types"
import { useApiMode } from "@/lib/api/client"
import { MERAH_SHIFT_SCENARIO, SPOTLIGHT } from "@/lib/mock/scenario"
import {
  findZoneByName,
  formatTension,
  getFleetWaitAvg,
  getShiftAttainment,
  getZoneOccupancy,
} from "@/lib/mock/scenarioMetrics"
import { shiftProductionRollup, type ProductionByShift } from "@/lib/production/mergeProduction"

export type DispatchActionKind = "rebalance" | "cycle_wait" | "shovel_assign" | "divert_dump"

export const DISPATCH_KIND_LABEL: Record<DispatchActionKind, string> = {
  rebalance: "Rééquilibrage dispatch",
  cycle_wait: "Réduire attente cycle",
  shovel_assign: "Réaffectation pelle",
  divert_dump: "Divertissement décharge",
}

export interface DispatchRecommendation {
  id: string
  kind: DispatchActionKind
  title: string
  why: string
  evidence: string[]
  action: string
  impactTonsPerHour: number
  impactWaitMin: number
  confidence: number
  equipmentIds: string[]
  zoneIds: string[]
}

export interface ZonePressure {
  zoneId: string
  name: string
  count: number
  capacity: number
  ratio: number
}

export interface DispatchObjective {
  attainmentPct: number | null
  tonnage: number | null
  target: number | null
  lostTonsFromWait: number
  predictedGainTonsPerHour: number
  avgWaitMin: number
}

export interface DispatchSimSnapshot {
  avgWaitMin: number
  avgCycleMin: number
  zonePressures: ZonePressure[]
  attainmentPct: number | null
}

export interface DispatchOptimizationBundle {
  summary: AiInsight
  objective: DispatchObjective
  recommendations: DispatchRecommendation[]
  baseline: DispatchSimSnapshot
}

function hashString(s: string): number {
  let h = 0
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0
  return Math.abs(h)
}

function confidenceFrom(seed: string, min = 70, max = 94) {
  return min + (hashString(seed) % Math.max(1, max - min))
}

export function computeZonePressures(equipment: Equipment[], zones: Zone[]): ZonePressure[] {
  return zones
    .filter((z) => z.capacity != null && z.capacity > 0)
    .map((z) => {
      const occ = getZoneOccupancy(equipment, z)!
      return {
        zoneId: z.id,
        name: z.name,
        count: occ.count,
        capacity: occ.capacity,
        ratio: occ.ratio,
      }
    })
    .sort((a, b) => b.ratio - a.ratio)
}

function trucksOf(equipment: Equipment[]) {
  return equipment.filter((e) => e.type === "haul_truck")
}

function isShovelAvailable(eq: Equipment): boolean {
  if (eq.code === SPOTLIGHT.excavatorMaint) return false
  if (!eq.engineOn) return false
  if (eq.state.startsWith("arret") || eq.state === "eteint" || eq.state === "aucune_donnee") return false
  return eq.type === "excavator" || eq.type === "loader"
}

function availableShovels(equipment: Equipment[]) {
  return equipment.filter(isShovelAvailable)
}

function tensionLabel(p: ZonePressure): string {
  return formatTension({
    zoneId: p.zoneId,
    name: p.name,
    count: p.count,
    capacity: p.capacity,
    ratio: p.ratio,
    pct: Math.round(p.ratio * 100),
    label: "",
  })
}

export function buildBaselineSnapshot(
  equipment: Equipment[],
  zones: Zone[],
  _production: ProductionRecord[]
): DispatchSimSnapshot {
  if (useApiMode) {
    throw new Error("buildBaselineSnapshot is mock-only")
  }
  const att = getShiftAttainment()
  const trucks = trucksOf(equipment)
  const avgWaitMin = getFleetWaitAvg(equipment, SPOTLIGHT.siteId)
  const avgCycleMin =
    trucks.length === 0
      ? 0
      : trucks.reduce(
          (s, t) =>
            s + (t.tripsThisShift > 0 ? 480 / t.tripsThisShift : (t.cycleDureeMoyenneMin ?? 0)),
          0
        ) / trucks.length
  return {
    avgWaitMin,
    avgCycleMin: Number(avgCycleMin.toFixed(1)),
    zonePressures: computeZonePressures(equipment, zones).slice(0, 5),
    attainmentPct: att.attainmentPct,
  }
}

export function projectSnapshot(
  baseline: DispatchSimSnapshot,
  recs: DispatchRecommendation[]
): DispatchSimSnapshot {
  const waitCut = recs.reduce((s, r) => s + r.impactWaitMin, 0)
  const tonsGain = recs.reduce((s, r) => s + r.impactTonsPerHour, 0)
  const projectedPressures = baseline.zonePressures.map((z, i) => {
    const touched = recs.some((r) => r.zoneIds.includes(z.zoneId))
    const relief = touched ? 0.18 + (i === 0 ? 0.12 : 0.05) : 0.02
    return {
      ...z,
      ratio: Math.max(0.35, z.ratio * (1 - relief)),
      count: Math.max(0, Math.round(z.count * (1 - relief * 0.5))),
    }
  })
  return {
    avgWaitMin: Number(Math.max(2, baseline.avgWaitMin - waitCut * 0.35).toFixed(1)),
    avgCycleMin: Number(Math.max(8, baseline.avgCycleMin - waitCut * 0.25).toFixed(1)),
    zonePressures: projectedPressures.sort((a, b) => b.ratio - a.ratio),
    attainmentPct:
      baseline.attainmentPct == null
        ? null
        : Number(Math.min(112, baseline.attainmentPct + tonsGain * 0.55).toFixed(1)),
  }
}

/**
 * Builds a dispatch/cycle optimization bundle from live mock fleet state.
 * Deterministic per site — no backend / LangGraph yet.
 */
export function dispatchOptimizationBundle(
  siteId: string,
  equipment: Equipment[],
  zones: Zone[],
  productionByShift: ProductionByShift,
  idleThresholdMin: number
): DispatchOptimizationBundle {
  if (useApiMode) {
    const rollup = shiftProductionRollup(productionByShift)
    const tonnage = rollup.actual
    const target = rollup.target
    const attainmentPct = rollup.attainmentPct
    const trucks = equipment.filter((e) => e.type === "haul_truck" && (!siteId || e.siteId === siteId))
    const avgWait =
      trucks.length === 0
        ? 0
        : Number(
            (trucks.reduce((s, t) => s + t.waitingMinutesThisShift, 0) / trucks.length).toFixed(1)
          )
    const baseline: DispatchSimSnapshot = {
      avgWaitMin: avgWait,
      avgCycleMin: 0,
      zonePressures: computeZonePressures(equipment, zones),
      attainmentPct,
    }
    return {
      summary: {
        title: "Moteur de recommandations non activé",
        body: "Les recommandations de dispatch nécessitent le moteur IA LangGraph. Données opérationnelles actuelles uniquement.",
      },
      objective: {
        attainmentPct,
        tonnage,
        target,
        lostTonsFromWait: 0,
        predictedGainTonsPerHour: 0,
        avgWaitMin: avgWait,
      },
      recommendations: [],
      baseline,
    }
  }
  const trucks = trucksOf(equipment)
  const shovels = availableShovels(equipment)
  const pressures = computeZonePressures(equipment, zones)
  const hot = pressures.filter((p) => p.ratio >= 0.7)
  const cold = [...pressures].filter((p) => p.ratio < 0.55).reverse()
  const waiting = [...trucks].sort((a, b) => b.waitingMinutesThisShift - a.waitingMinutesThisShift)
  const topWait = waiting.slice(0, 4)

  const att = getShiftAttainment()
  const tonnage = att.actual
  const target = att.target
  const attainmentPct = att.attainmentPct
  const avgWait = getFleetWaitAvg(equipment, siteId)
  const lostTonsFromWait = Number((avgWait * trucks.length * 0.15).toFixed(0))

  const dumpZones = zones.filter((z) => z.type === "dechargement" || z.type === "concasseur")
  const loadZones = zones.filter((z) => z.type === "chargement")
  const hotLoad = hot.find((h) => loadZones.some((z) => z.id === h.zoneId)) ?? hot[0]
  const coldLoad = cold.find((c) => loadZones.some((z) => z.id === c.zoneId)) ?? cold[0]
  const hotDump =
    pressures.find((p) => dumpZones.some((z) => z.id === p.zoneId) && p.ratio >= 0.65) ??
    pressures.find((p) => dumpZones.some((z) => z.id === p.zoneId))
  const altDump = dumpZones.find((z) => z.id !== hotDump?.zoneId) ?? dumpZones[1]

  const seed = `${siteId}-${hotLoad?.zoneId ?? "x"}-${topWait[0]?.id ?? "y"}`
  const recommendations: DispatchRecommendation[] = []

  const bancB = findZoneByName(zones, SPOTLIGHT.bancBName, siteId)
  const bancA = findZoneByName(zones, SPOTLIGHT.bancAName, siteId)
  const bancBOcc = getZoneOccupancy(equipment, bancB)

  if (siteId === SPOTLIGHT.siteId && bancB && bancA) {
    const moveCount = MERAH_SHIFT_SCENARIO.optimisation.trucksToMove
    const bTrucks = trucks.filter((t) => t.zoneId === bancB.id).slice(0, moveCount)
    recommendations.push({
      id: `rebalance-${bancB.id}-${bancA.id}`,
      kind: "rebalance",
      title: `Rediriger ${moveCount} camions ${SPOTLIGHT.bancBName} → ${SPOTLIGHT.bancAName}`,
      why: `${SPOTLIGHT.bancBName} est saturé (${bancBOcc?.label ?? "7/3"}) depuis 10:30 alors que ${SPOTLIGHT.excavatorMaint} est en maintenance. ${SPOTLIGHT.bancAName} reste sous-utilisé.`,
      evidence: [
        bancBOcc ? formatTension(bancBOcc) : `File ${MERAH_SHIFT_SCENARIO.congestion.truckCount} · cap. 3`,
        `${SPOTLIGHT.excavatorMaint} arrêt matériel — non disponible`,
        `Objectif ${target.toLocaleString("fr-FR")} t · réel ${tonnage.toLocaleString("fr-FR")} t (−${att.gapPct} %)`,
      ],
      action: MERAH_SHIFT_SCENARIO.narrative.action,
      impactTonsPerHour: 28,
      impactWaitMin: 8,
      confidence: 90,
      equipmentIds: bTrucks.map((t) => t.id),
      zoneIds: [bancB.id, bancA.id],
    })
  }

  if (hotLoad && coldLoad && hotLoad.zoneId !== coldLoad.zoneId) {
    const already =
      bancB && bancA && hotLoad.zoneId === bancB.id && coldLoad.zoneId === bancA.id
    if (!already) {
      const moveCount = Math.min(4, Math.max(2, Math.round(hotLoad.count * 0.25)))
      recommendations.push({
        id: `rebalance-${hotLoad.zoneId}-${coldLoad.zoneId}`,
        kind: "rebalance",
        title: `Rééquilibrer ${moveCount} camions vers ${coldLoad.name}`,
        why: `${hotLoad.name} est en tension (${hotLoad.count}/${hotLoad.capacity}) alors que ${coldLoad.name} reste sous-utilisé.`,
        evidence: [
          tensionLabel(hotLoad),
          `${coldLoad.name} : ${coldLoad.count}/${coldLoad.capacity}`,
          `Seuil d'inactivité poste : ${idleThresholdMin} min`,
        ],
        action: `Déplacer ${moveCount} camions de ${hotLoad.name} vers ${coldLoad.name} pour le reste du poste.`,
        impactTonsPerHour: 18 + (hashString(seed) % 14),
        impactWaitMin: 4 + (hashString(`${seed}-w`) % 6),
        confidence: confidenceFrom(seed),
        equipmentIds: trucks.filter((t) => t.zoneId === hotLoad.zoneId).slice(0, moveCount).map((t) => t.id),
        zoneIds: [hotLoad.zoneId, coldLoad.zoneId],
      })
    }
  }

  if (topWait.length > 0) {
    const codes = topWait
      .slice(0, 3)
      .map((t) => t.code)
      .join(", ")
    recommendations.push({
      id: `cycle-wait-${topWait[0].id}`,
      kind: "cycle_wait",
      title: "Couper les attentes de chargement anormales",
      why: `${topWait.length} camions dépassent nettement la moyenne d'attente du poste (${avgWait.toFixed(0)} min).`,
      evidence: [
        `Top attentes : ${codes}`,
        `${topWait[0].code} — ${topWait[0].waitingMinutesThisShift.toFixed(0)} min d'attente`,
        `Moyenne flotte ${avgWait.toFixed(0)} min`,
      ],
      action: "Prioriser le dispatch sur ces camions et libérer la file amont.",
      impactTonsPerHour: 12 + (hashString(`${seed}-c`) % 10),
      impactWaitMin: 6 + (hashString(`${seed}-cw`) % 8),
      confidence: confidenceFrom(`${seed}-cycle`),
      equipmentIds: topWait.slice(0, 3).map((t) => t.id),
      zoneIds: [...new Set(topWait.slice(0, 3).map((t) => t.zoneId).filter(Boolean))] as string[],
    })
  }

  const shovelBusyZone = hotLoad
  const spare = shovelBusyZone
    ? shovels.find((s) => s.zoneId !== shovelBusyZone.zoneId) ??
      shovels.find((s) => s.code !== SPOTLIGHT.excavatorMaint)
    : undefined
  if (shovelBusyZone && spare) {
    const localShovels = shovels.filter((s) => s.zoneId === shovelBusyZone.zoneId)
    recommendations.push({
      id: `shovel-${shovelBusyZone.zoneId}-${spare.id}`,
      kind: "shovel_assign",
      title: `Renforcer ${shovelBusyZone.name} avec une pelle`,
      why:
        localShovels.length <= 1
          ? `Capacité de chargement insuffisante sur ${shovelBusyZone.name} (EXC-027 en maintenance — non disponible).`
          : `La capacité de chargement sur ${shovelBusyZone.name} ne suit pas le flux camion.`,
      evidence: [
        `${localShovels.length} pelle(s) disponible(s) sur zone`,
        `Disponible : ${spare.code}`,
        `${SPOTLIGHT.excavatorMaint} exclu (maintenance)`,
        tensionLabel(shovelBusyZone),
      ],
      action: `Réaffecter temporairement ${spare.code} sur ${shovelBusyZone.name}.`,
      impactTonsPerHour: 22 + (hashString(`${seed}-s`) % 12),
      impactWaitMin: 5 + (hashString(`${seed}-sw`) % 5),
      confidence: confidenceFrom(`${seed}-shovel`),
      equipmentIds: [spare.id, ...trucks.filter((t) => t.zoneId === shovelBusyZone.zoneId).slice(0, 2).map((t) => t.id)],
      zoneIds: [shovelBusyZone.zoneId, spare.zoneId].filter(Boolean) as string[],
    })
  }

  if (hotDump && altDump) {
    recommendations.push({
      id: `divert-${hotDump.zoneId}-${altDump.id}`,
      kind: "divert_dump",
      title: `Divertir une partie du flux vers ${altDump.name}`,
      why: `${hotDump.name} concentre la file de déchargement et allonge le cycle retour.`,
      evidence: [
        tensionLabel(hotDump),
        `Alternative : ${altDump.name}`,
        "Cause principale = file, pas panne matériel",
      ],
      action: `Orienter 30–40 % des camions chargés vers ${altDump.name} jusqu'à 1h.`,
      impactTonsPerHour: 10 + (hashString(`${seed}-d`) % 9),
      impactWaitMin: 3 + (hashString(`${seed}-dw`) % 5),
      confidence: confidenceFrom(`${seed}-divert`),
      equipmentIds: trucks
        .filter((t) => t.destinationZoneId === hotDump.zoneId || t.zoneId === hotDump.zoneId)
        .slice(0, 4)
        .map((t) => t.id),
      zoneIds: [hotDump.zoneId, altDump.id],
    })
  }

  while (recommendations.length < 4) {
    const i = recommendations.length
    recommendations.push({
      id: `fallback-${siteId}-${i}`,
      kind: "cycle_wait",
      title: "Stabiliser les cycles longs du poste",
      why: "Plusieurs cycles dépassent la durée moyenne — un réordonnancement léger du dispatch peut récupérer du tonnage.",
      evidence: ["Écart cycle vs moyenne poste", "Attentes cumulées en hausse"],
      action: "Préparer un lissage du dispatch sur les 2 prochaines heures.",
      impactTonsPerHour: 8 + i * 2,
      impactWaitMin: 3 + i,
      confidence: 72 + i * 3,
      equipmentIds: trucks.slice(i, i + 2).map((t) => t.id),
      zoneIds: zones.slice(0, 2).map((z) => z.id),
    })
  }

  const ranked = recommendations
    .slice(0, 6)
    .sort((a, b) => b.impactTonsPerHour + b.impactWaitMin * 1.2 - (a.impactTonsPerHour + a.impactWaitMin * 1.2))

  const predictedGainTonsPerHour = ranked.slice(0, 3).reduce((s, r) => s + r.impactTonsPerHour, 0)

  const summary: AiInsight = {
    title: MERAH_SHIFT_SCENARIO.narrative.headline,
    body: MERAH_SHIFT_SCENARIO.narrative.body,
    confidence: confidenceFrom(seed, 74, 95),
    evidence: [
      `Atteinte ${attainmentPct.toFixed(1)} % (${tonnage.toLocaleString("fr-FR")} / ${target.toLocaleString("fr-FR")} t)`,
      bancBOcc ? formatTension(bancBOcc) : "Banc B saturé",
      `Attente moyenne flotte ${avgWait.toFixed(0)} min`,
    ],
    next: MERAH_SHIFT_SCENARIO.narrative.next,
    action: ranked[0]?.action ?? MERAH_SHIFT_SCENARIO.narrative.action,
  }

  const baseline = buildBaselineSnapshot(equipment, zones, productionByShift.hourly)

  return {
    summary,
    objective: {
      attainmentPct,
      tonnage,
      target,
      lostTonsFromWait,
      predictedGainTonsPerHour: Number(predictedGainTonsPerHour.toFixed(0)),
      avgWaitMin: avgWait,
    },
    recommendations: ranked,
    baseline,
  }
}
