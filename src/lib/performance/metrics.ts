import type { Equipment, ProductionRecord, Zone, DowntimeReason } from "@/lib/mock/types"
import {
  CYCLE_STAGE_LABEL,
  EQUIPMENT_TYPE_LABEL,
  FILM_STATE_GROUP,
  cycleTotalMinutes,
} from "@/lib/mock/types"
import { useApiMode } from "@/lib/api/client"
import {
  merahDowntimeFacts,
  merahDowntimeKpis,
  merahDowntimeSpotlightRows,
  merahProductionFacts,
  merahWaitingBancBKpi,
  merahWaitingFacts,
} from "@/lib/mock/performanceFacts"
import { getFleetWaitAvg, getShiftProduction } from "@/lib/mock/scenarioMetrics"
import { shiftProductionRollup } from "@/lib/production/mergeProduction"
import type { PerformanceMetric } from "@/lib/workspace/types"
import { performanceMetricLabel } from "@/lib/workspace/titles"

export interface PerfKpi {
  id: string
  label: string
  value: string
  hint?: string
  tone?: "good" | "warn" | "bad" | "neutral"
}

export interface PerfInterpretation {
  facts: string[]
  inference: string
  missing: string[]
  confidence: number
}

export interface PerfColumn {
  id: string
  header: string
  accessorKey: string
}

export interface PerfAnalysis {
  metric: PerformanceMetric
  title: string
  kpis: PerfKpi[]
  chartKind: "line" | "bar" | "hbar" | "stacked" | "histogram"
  chartData: Record<string, string | number | null>[]
  chartSeries: { key: string; name: string; color?: string }[]
  columns: PerfColumn[]
  rows: Record<string, string | number | null>[]
  interpretation: PerfInterpretation
  fuelMode?: "lph" | "lpt" | "idle"
}

const COLORS = ["#1d8943", "#3a7bd5", "#d97706", "#9a9a9a", "#7a6aad"]

export function buildPerformanceAnalysis(input: {
  metric: PerformanceMetric
  equipment: Equipment[]
  zones: Zone[]
  productionHourly: ProductionRecord[]
  productionShiftly?: ProductionRecord[]
  downtimeReasons: DowntimeReason[]
  siteId?: string
  fuelMode?: "lph" | "lpt" | "idle"
}): PerfAnalysis {
  const { metric, equipment, zones, productionHourly, productionShiftly, downtimeReasons, siteId } = input
  const fuelMode = input.fuelMode ?? "lph"
  const cycleTargetMin = productionShiftly?.[0]?.targetCycleMin ?? null
  let analysis: PerfAnalysis
  switch (metric) {
    case "production":
      analysis = buildProduction(productionHourly, equipment, productionShiftly)
      break
    case "fuel":
      analysis = buildFuel(equipment, fuelMode)
      break
    case "cycle":
      analysis = buildCycle(equipment, zones, cycleTargetMin)
      break
    case "waiting":
      analysis = buildWaiting(equipment, zones, siteId)
      break
    case "td":
      analysis = buildTd(equipment)
      break
    case "tu":
      analysis = buildTu(equipment)
      break
    case "voyages":
      analysis = buildVoyages(equipment)
      break
    case "downtime":
      analysis = buildDowntime(equipment, downtimeReasons)
      break
    default:
      analysis = buildProduction(productionHourly, equipment)
  }
  return { ...analysis, kpis: analysis.kpis.slice(0, 3) }
}

function buildProduction(
  hourly: ProductionRecord[],
  equipment: Equipment[],
  productionShiftly?: ProductionRecord[]
): PerfAnalysis {
  const shift = useApiMode
    ? (() => {
        const rollup = shiftProductionRollup({
          hourly,
          daily: [],
          shiftly: productionShiftly ?? [],
        })
        return {
          actual: rollup.actual,
          target: rollup.target,
          attainmentPct: rollup.attainmentPct,
          gapTons: rollup.gapTons,
          hourly,
        }
      })()
    : getShiftProduction(hourly)
  const trucks = equipment.filter((e) => e.type === "haul_truck")
  const trips = trucks.reduce((s, e) => s + e.tripsThisShift, 0)
  const delay = trucks.reduce((s, e) => s + e.waitingMinutesThisShift, 0)

  const chartData = shift.hourly.map((r) => ({
    hour: r.label,
    actual: r.tonnage,
    target: useApiMode ? (r.target ?? null) : (r.target ?? 0),
    ecart: r.target != null ? r.tonnage - r.target : useApiMode ? null : r.tonnage,
  }))

  const rows = shift.hourly.map((r) => ({
    hour: r.label,
    actual: r.tonnage,
    target: useApiMode ? (r.target ?? "—") : (r.target ?? 0),
    ecart: r.target != null ? r.tonnage - r.target : useApiMode ? "—" : r.tonnage,
    trips: useApiMode ? (r.trips != null ? r.trips : "—") : Math.round(trips / Math.max(1, shift.hourly.length)),
    trucks: trucks.length,
    delayMin: useApiMode
      ? r.delayMin != null
        ? r.delayMin
        : "—"
      : Math.round(delay / Math.max(1, shift.hourly.length)),
  }))

  return {
    metric: "production",
    title: performanceMetricLabel("production"),
    kpis: [
      {
        id: "actual",
        label: "Réel",
        value: shift.actual != null ? `${shift.actual.toLocaleString("fr-FR")} t` : "—",
        tone: "warn",
      },
      {
        id: "target",
        label: "Objectif",
        value: shift.target != null ? `${shift.target.toLocaleString("fr-FR")} t` : "—",
      },
      {
        id: "attain",
        label: "Atteinte",
        value: shift.attainmentPct != null ? `${shift.attainmentPct.toFixed(1)} %` : "—",
        tone:
          shift.attainmentPct != null && shift.attainmentPct >= 95
            ? "good"
            : shift.attainmentPct != null
              ? "warn"
              : "neutral",
      },
      {
        id: "gap",
        label: "Écart",
        value: shift.gapTons != null ? `−${shift.gapTons.toLocaleString("fr-FR")} t` : "—",
        tone: "bad",
      },
    ],
    chartKind: "line",
    chartData,
    chartSeries: [
      { key: "actual", name: "Réel", color: COLORS[0] },
      { key: "target", name: "Objectif", color: COLORS[1] },
    ],
    columns: [
      { id: "hour", header: "Heure", accessorKey: "hour" },
      { id: "actual", header: "Réel (t)", accessorKey: "actual" },
      { id: "target", header: "Objectif (t)", accessorKey: "target" },
      { id: "ecart", header: "Écart", accessorKey: "ecart" },
      { id: "trips", header: "Voyages", accessorKey: "trips" },
      { id: "trucks", header: "Camions", accessorKey: "trucks" },
      { id: "delayMin", header: "Retard (min)", accessorKey: "delayMin" },
    ],
    rows,
    interpretation: {
      facts: useApiMode
        ? [
            shift.actual != null
              ? `${shift.actual.toLocaleString("fr-FR")} t réalisé`
              : "Réel non défini",
            shift.target != null
              ? `${shift.target.toLocaleString("fr-FR")} t objectif (${shift.attainmentPct ?? "—"} %)`
              : "Objectif non défini",
            `${trucks.length} camions · ${trips} voyages`,
          ]
        : merahProductionFacts(shift.actual ?? 0, shift.target, shift.attainmentPct),
      inference: useApiMode
        ? "Interprétation IA non activée — chiffres issus de la production simulée."
        : "La file Banc B et EXC-027 en maintenance expliquent la majorité de l'écart de poste.",
      missing: useApiMode
        ? ["Moteur d'analyse Performance non activé"]
        : ["Répartition tonnage par banc (A vs B)", "Retard imputable uniquement à l'attente"],
      confidence: useApiMode ? 0 : 88,
    },
  }
}

function buildFuel(equipment: Equipment[], mode: "lph" | "lpt" | "idle"): PerfAnalysis {
  const active = equipment.filter((e) => e.engineOn === true || (e.gasoilLph ?? 0) > 0)
  const withFuel = active.filter((e) => e.gasoilLph != null)
  const fleetAvgLph =
    withFuel.length === 0
      ? 0
      : withFuel.reduce((s, e) => s + (e.gasoilLph ?? 0), 0) / withFuel.length
  const rows = [...active]
    .map((e) => {
      const lph = e.gasoilLph
      if (useApiMode) {
        const ecart = lph != null && fleetAvgLph > 0 ? Number((lph - fleetAvgLph).toFixed(1)) : null
        return {
          code: e.code,
          type: EQUIPMENT_TYPE_LABEL[e.type],
          hours: "—",
          litres: "—",
          lph: lph ?? "—",
          lpt: "—",
          idleL: "—",
          ecart,
          sort: lph ?? 0,
        }
      }
      if (!useApiMode) {
        const hours = Math.max(0.5, ((e.engineHours ?? 0) % 24) || 6)
        const lphVal = lph ?? 0
        const litres = Math.round(lphVal * hours)
        const cap = e.capacityTons ?? 0
        const tons = Math.max(1, e.tripsThisShift * Math.max(1, e.payloadTons ?? (cap > 0 ? cap * 0.85 : 0)))
        const lpt = tons > 0 ? Number((litres / tons).toFixed(2)) : null
        const idleL = Math.round((e.idleMinutesThisShift / 60) * lphVal * 0.35)
        const ecart = fleetAvgLph > 0 ? Number((lphVal - fleetAvgLph).toFixed(1)) : null
        return {
          code: e.code,
          type: EQUIPMENT_TYPE_LABEL[e.type],
          hours: Number(hours.toFixed(1)),
          litres,
          lph: lphVal,
          lpt,
          idleL,
          ecart,
          sort: mode === "lph" ? lphVal : mode === "lpt" ? (lpt ?? 0) : idleL,
        }
      }
      return {
        code: e.code,
        type: EQUIPMENT_TYPE_LABEL[e.type],
        hours: "—",
        litres: "—",
        lph: "—",
        lpt: "—",
        idleL: "—",
        ecart: null,
        sort: 0,
      }
    })
    .sort((a, b) => Number(b.sort) - Number(a.sort))
    .slice(0, 14)

  const chartKey = mode === "lph" ? "lph" : mode === "lpt" ? "lpt" : "idleL"
  const chartName = mode === "lph" ? "l/h" : mode === "lpt" ? "L/t" : "Idle L"

  const numericLphRows = rows.filter((r) => typeof r.lph === "number")
  const totalL = useApiMode
    ? null
    : rows.reduce((s, r) => s + Number(r.litres), 0)
  const avgLph =
    numericLphRows.length === 0
      ? null
      : numericLphRows.reduce((s, r) => s + Number(r.lph), 0) / numericLphRows.length
  const idleTotal = useApiMode
    ? null
    : rows.reduce((s, r) => s + Number(r.idleL), 0)

  const chartData = useApiMode
    ? numericLphRows.map((r) => ({ name: r.code, lph: r.lph as number }))
    : rows.map((r) => ({ name: r.code, [chartKey]: r[chartKey as keyof typeof r] as number }))

  return {
    metric: "fuel",
    title: performanceMetricLabel("fuel"),
    fuelMode: mode,
    kpis: [
      {
        id: "total",
        label: useApiMode ? "Gasoil" : "Gasoil estimé",
        value: totalL != null ? `${totalL.toLocaleString("fr-FR")} L` : "—",
      },
      {
        id: "avg",
        label: "Moy. l/h",
        value: avgLph != null ? avgLph.toFixed(1) : "—",
        hint: "flotte active",
      },
      {
        id: "idle",
        label: useApiMode ? "Idle" : "Idle estimé",
        value: idleTotal != null ? `${idleTotal} L` : "—",
        tone: "warn",
      },
      { id: "units", label: "Engins", value: String(rows.length) },
    ],
    chartKind: "bar",
    chartData,
    chartSeries: [{ key: useApiMode ? "lph" : chartKey, name: chartName, color: COLORS[2] }],
    columns: [
      { id: "code", header: "Équipement", accessorKey: "code" },
      { id: "type", header: "Type", accessorKey: "type" },
      { id: "hours", header: "Heures", accessorKey: "hours" },
      { id: "litres", header: "Litres", accessorKey: "litres" },
      { id: "lph", header: "l/h", accessorKey: "lph" },
      { id: "lpt", header: "L/t", accessorKey: "lpt" },
      { id: "idleL", header: "Idle L", accessorKey: "idleL" },
      { id: "ecart", header: "Écart l/h", accessorKey: "ecart" },
    ],
    rows: rows.map(({ sort: _s, ...r }) => r),
    interpretation: {
      facts: useApiMode
        ? [
            `${numericLphRows.length} engins avec débit mesuré`,
            avgLph != null ? `Moyenne ${avgLph.toFixed(1)} l/h` : "Litres poste non calculés côté serveur",
          ]
        : [`${rows.length} engins avec consommation estimée`, `Total ~${totalL} L sur le poste`],
      inference: useApiMode
        ? "Interprétation IA non activée — écarts calculés vs moyenne flotte."
        : "Les camions en file Banc B consomment à l'idle sans produire de tonnage.",
      missing: useApiMode
        ? ["Moteur d'analyse Performance non activé"]
        : ["Mesure débitmètre réelle", "Calibration L/t par modèle"],
      confidence: useApiMode ? 0 : 74,
    },
  }
}

function stageMin(stages: Equipment["cycleActuel"], key: string): number {
  return stages.find((s) => s.key === key)?.minutes ?? 0
}

function buildCycle(equipment: Equipment[], zones: Zone[], cycleTargetMin: number | null): PerfAnalysis {
  const trucks = equipment.filter((e) => e.type === "haul_truck")
  const zoneName = (id: string | null) => zones.find((z) => z.id === id)?.name ?? "—"
  const target = useApiMode ? cycleTargetMin : 38

  const rows = trucks
    .map((e) => {
      const stages = e.cycleActuel ?? []
      const longest = [...stages]
        .filter((s) => s.minutes != null)
        .sort((a, b) => (b.minutes ?? 0) - (a.minutes ?? 0))[0]
      const avg = useApiMode
        ? e.cycleDureeMoyenneMin
        : e.cycleDureeMoyenneMin ??
          (cycleTotalMinutes(stages) || (e.tripsThisShift > 0 ? 480 / e.tripsThisShift : null))
      const od = `${zoneName(e.zoneId)} → ${zoneName(e.destinationZoneId)}`
      const waitRaw =
        stageMin(stages, "attente_charge") + stageMin(stages, "attente_dechargement")
      const wait = useApiMode
        ? waitRaw > 0
          ? waitRaw
          : e.waitingMinutesThisShift
        : waitRaw > 0
          ? waitRaw
          : e.tripsThisShift > 0
            ? e.waitingMinutesThisShift / e.tripsThisShift
            : e.waitingMinutesThisShift
      return {
        code: e.code,
        od,
        cycles: e.tripsThisShift,
        avg: avg != null ? Number(avg.toFixed(1)) : null,
        target: target ?? "—",
        longestStage: longest ? CYCLE_STAGE_LABEL[longest.key] : "—",
        wait,
        haul: stageMin(stages, "vide") + stageMin(stages, "charge"),
        load: stageMin(stages, "chargement"),
        dump: stageMin(stages, "dechargement"),
      }
    })
    .sort((a, b) => Number(b.avg ?? 0) - Number(a.avg ?? 0))
    .slice(0, 12)

  const chartData = rows.slice(0, 8).map((r) => ({
    name: r.code,
    wait: Number(r.wait) || 0,
    load: Number(r.load) || 0,
    haul: Number(r.haul) || 0,
    dump: Number(r.dump) || 0,
  }))

  const withAvg = rows.filter((r) => r.avg != null)
  const avgCycle =
    withAvg.length === 0 ? 0 : withAvg.reduce((s, r) => s + Number(r.avg), 0) / withAvg.length

  const targetLabel = target != null ? `${target} min` : "—"

  return {
    metric: "cycle",
    title: performanceMetricLabel("cycle"),
    kpis: [
      {
        id: "avg",
        label: "Cycle moy.",
        value: avgCycle > 0 ? `${avgCycle.toFixed(0)} min` : "—",
        tone: target != null && avgCycle > target + 4 ? "bad" : "warn",
      },
      { id: "target", label: "Cible", value: targetLabel },
      { id: "trips", label: "Voyages", value: String(rows.reduce((s, r) => s + Number(r.cycles), 0)) },
      { id: "trucks", label: "Camions", value: String(rows.length) },
    ],
    chartKind: "stacked",
    chartData,
    chartSeries: [
      { key: "wait", name: "Attente", color: COLORS[2] },
      { key: "load", name: "Chargement", color: COLORS[0] },
      { key: "haul", name: "Trajet", color: COLORS[1] },
      { key: "dump", name: "Déchargement", color: COLORS[3] },
    ],
    columns: [
      { id: "code", header: "Équipement", accessorKey: "code" },
      { id: "od", header: "OD", accessorKey: "od" },
      { id: "cycles", header: "Cycles", accessorKey: "cycles" },
      { id: "avg", header: "Moy. (min)", accessorKey: "avg" },
      { id: "target", header: "Cible", accessorKey: "target" },
      { id: "longestStage", header: "Étape longue", accessorKey: "longestStage" },
    ],
    rows,
    interpretation: {
      facts: useApiMode
        ? [
            avgCycle > 0 ? `Cycle moyen ~${avgCycle.toFixed(0)} min` : "Cycle moyen indisponible",
            target != null ? `Cible poste ${target} min` : "Cible cycle non définie",
          ]
        : [`Cycle moyen ~${avgCycle.toFixed(0)} min (cible 38)`, "Hausse après 11:00"],
      inference: useApiMode
        ? "Interprétation IA non activée — étapes dérivées des cycles actifs."
        : "L'attente de chargement Banc B allonge le cycle — EXC-027 hors service.",
      missing: useApiMode
        ? ["Moteur d'analyse Performance non activé"]
        : ["Ventilation minute par minute des étapes pour tous les camions"],
      confidence: useApiMode ? 0 : 82,
    },
  }
}

function meanKnownPct(values: Array<number | null | undefined>): number | null {
  const known = values.filter((v): v is number => typeof v === "number" && Number.isFinite(v))
  if (known.length === 0) return null
  return Math.round(known.reduce((s, v) => s + v, 0) / known.length)
}

function buildWaiting(equipment: Equipment[], zones: Zone[], siteId?: string): PerfAnalysis {
  const trucks = equipment.filter((e) => e.type === "haul_truck")
  const avgWait = useApiMode
    ? trucks.length === 0
      ? 0
      : Number(
          (trucks.reduce((s, t) => s + t.waitingMinutesThisShift, 0) / trucks.length).toFixed(1)
        )
    : getFleetWaitAvg(equipment, siteId)
  const scopedZones = zones.filter((z) => z.capacity > 0 && (!siteId || z.siteId === siteId))

  const rows = scopedZones
    .map((z) => {
      const inZone = trucks.filter((e) => e.zoneId === z.id)
      const count = inZone.length
      const avg = inZone.length
        ? inZone.reduce((s, e) => s + e.waitingMinutesThisShift, 0) / inZone.length
        : useApiMode
          ? 0
          : count / z.capacity >= 1
            ? 35
            : 12
      const maxQ = Math.max(count, z.capacity)
      const lost = useApiMode
        ? Math.round(avg * count)
        : Math.round(avg * Math.max(1, inZone.length))
      return {
        zone: z.name,
        avgQueue: useApiMode ? count : Number((count || avg / 10).toFixed(1)),
        maxQueue: maxQ,
        waitMin: Number(avg.toFixed(0)),
        trucks: count,
        lostTime: lost,
      }
    })
    .sort((a, b) => Number(b.waitMin) - Number(a.waitMin))

  return {
    metric: "waiting",
    title: performanceMetricLabel("waiting"),
    kpis: [
      { id: "avg", label: "Attente moy.", value: `${avgWait.toFixed(0)} min`, tone: "bad" },
      {
        id: "bancb",
        label: useApiMode ? "File max" : "File Banc B",
        value: useApiMode
          ? `${rows[0] ? `${rows[0].maxQueue}` : "—"}`
          : merahWaitingBancBKpi(),
        tone: "bad",
      },
      { id: "lost", label: "Temps perdu", value: `${rows.reduce((s, r) => s + Number(r.lostTime), 0)} min` },
      { id: "zones", label: "Zones", value: String(rows.length) },
    ],
    chartKind: "hbar",
    chartData: rows.slice(0, 8).map((r) => ({ name: r.zone, wait: r.waitMin })),
    chartSeries: [{ key: "wait", name: "Attente (min)", color: COLORS[2] }],
    columns: [
      { id: "zone", header: "Zone", accessorKey: "zone" },
      { id: "avgQueue", header: "File moy.", accessorKey: "avgQueue" },
      { id: "maxQueue", header: "File max", accessorKey: "maxQueue" },
      { id: "waitMin", header: "Attente (min)", accessorKey: "waitMin" },
      { id: "trucks", header: "Camions", accessorKey: "trucks" },
      { id: "lostTime", header: "Temps perdu", accessorKey: "lostTime" },
    ],
    rows,
    interpretation: {
      facts: useApiMode
        ? [`Attente flotte ~${avgWait.toFixed(0)} min`, `${rows.length} zones avec file`]
        : merahWaitingFacts(avgWait),
      inference: useApiMode
        ? "Interprétation IA non activée — files dérivées des états équipement."
        : "Rediriger une partie de la flotte Banc B → Banc A réduit l'attente sans saturer A.",
      missing: useApiMode
        ? ["Moteur d'analyse Performance non activé"]
        : ["Temps d'attente GPS précis par zone", "Capacité réelle Banc A à absorber"],
      confidence: useApiMode ? 0 : 90,
    },
  }
}

function buildTd(equipment: Equipment[]): PerfAnalysis {
  const types = Array.from(new Set(equipment.map((e) => e.type)))
  const rows = types.map((type) => {
    const inType = equipment.filter((e) => e.type === type)
    const td = meanKnownPct(inType.map((e) => e.tdPct))
    return {
      class: EQUIPMENT_TYPE_LABEL[type],
      count: inType.length,
      td,
    }
  })
  const avgTd = meanKnownPct(rows.map((r) => r.td))

  return {
    metric: "td",
    title: performanceMetricLabel("td"),
    kpis: [
      { id: "td", label: "TD moy.", value: avgTd != null ? `${avgTd} %` : "—", hint: "définition à confirmer" },
      {
        id: "best",
        label: "Meilleure classe",
        value:
          rows
            .filter((r) => r.td != null)
            .slice()
            .sort((a, b) => Number(b.td) - Number(a.td))[0]?.class ?? "—",
      },
      { id: "fleet", label: "Engins", value: String(equipment.length) },
    ],
    chartKind: "bar",
    chartData: rows.map((r) => ({ name: r.class, td: r.td })),
    chartSeries: [{ key: "td", name: "TD %", color: COLORS[1] }],
    columns: [
      { id: "class", header: "Classe", accessorKey: "class" },
      { id: "count", header: "Effectif", accessorKey: "count" },
      { id: "td", header: "TD %", accessorKey: "td" },
    ],
    rows,
    interpretation: {
      facts: [avgTd != null ? `TD moyen flotte ~${avgTd} %` : "TD moyen flotte indisponible"],
      inference: useApiMode
        ? "Interprétation IA non activée — TD calculé depuis les états équipement du poste."
        : "TD reflète la disponibilité déclarée — à croiser avec arrêts sans cause.",
      missing: useApiMode ? ["Moteur d'analyse Performance non activé"] : ["Définition métier exacte de TD (à confirmer)"],
      confidence: useApiMode ? 0 : 65,
    },
  }
}

function buildTu(equipment: Equipment[]): PerfAnalysis {
  const types = Array.from(new Set(equipment.map((e) => e.type)))
  const rows = types.map((type) => {
    const inType = equipment.filter((e) => e.type === type)
    const tu = meanKnownPct(inType.map((e) => e.tuPct))
    const active = inType.filter((e) => {
      const g = FILM_STATE_GROUP[e.state]
      return g !== "arret" && g !== "eteint" && g !== "aucune_donnee"
    }).length
    return {
      class: EQUIPMENT_TYPE_LABEL[type],
      count: inType.length,
      active,
      tu,
    }
  })
  const avgTu = meanKnownPct(rows.map((r) => r.tu))

  return {
    metric: "tu",
    title: performanceMetricLabel("tu"),
    kpis: [
      { id: "tu", label: "TU moy.", value: avgTu != null ? `${avgTu} %` : "—", hint: "définition à confirmer" },
      {
        id: "active",
        label: "Actifs maintenant",
        value: String(rows.reduce((s, r) => s + Number(r.active), 0)),
      },
      { id: "fleet", label: "Engins", value: String(equipment.length) },
    ],
    chartKind: "bar",
    chartData: rows.map((r) => ({ name: r.class, tu: r.tu })),
    chartSeries: [{ key: "tu", name: "TU %", color: COLORS[4] }],
    columns: [
      { id: "class", header: "Classe", accessorKey: "class" },
      { id: "count", header: "Effectif", accessorKey: "count" },
      { id: "active", header: "Actifs", accessorKey: "active" },
      { id: "tu", header: "TU %", accessorKey: "tu" },
    ],
    rows,
    interpretation: {
      facts: [avgTu != null ? `TU moyen flotte ~${avgTu} %` : "TU moyen flotte indisponible"],
      inference: useApiMode
        ? "Interprétation IA non activée — TU calculé depuis les états productifs du poste."
        : "Utilisation limitée par le goulot Banc B — camions en file sans produire.",
      missing: useApiMode ? ["Moteur d'analyse Performance non activé"] : ["Définition métier exacte de TU (à confirmer)"],
      confidence: useApiMode ? 0 : 65,
    },
  }
}

function buildVoyages(equipment: Equipment[]): PerfAnalysis {
  const trucks = equipment.filter((e) => e.type === "haul_truck")
  const total = trucks.reduce((s, e) => s + e.tripsThisShift, 0)
  const avg = trucks.length ? total / trucks.length : 0
  const rows = [...trucks]
    .map((e) => {
      const tons = useApiMode
        ? null
        : Math.round(e.tripsThisShift * (e.payloadTons || (e.capacityTons ?? 0) * 0.88))
      return {
        code: e.code,
        trips: e.tripsThisShift,
        wait: Math.round(e.waitingMinutesThisShift),
        cycle: e.cycleDureeMoyenneMin != null ? Number(e.cycleDureeMoyenneMin.toFixed(1)) : null,
        tons,
      }
    })
    .sort((a, b) => b.trips - a.trips)

  return {
    metric: "voyages",
    title: performanceMetricLabel("voyages"),
    kpis: [
      { id: "total", label: "Voyages", value: String(total) },
      { id: "avg", label: "Moy. / camion", value: avg.toFixed(1) },
      {
        id: "top",
        label: "Meilleur",
        value: rows[0] ? `${rows[0].code} (${rows[0].trips})` : "—",
      },
    ],
    chartKind: "bar",
    chartData: rows.slice(0, 10).map((r) => ({ name: r.code, trips: r.trips })),
    chartSeries: [{ key: "trips", name: "Voyages", color: COLORS[0] }],
    columns: [
      { id: "code", header: "Équipement", accessorKey: "code" },
      { id: "trips", header: "Voyages", accessorKey: "trips" },
      { id: "cycle", header: "Cycle moy.", accessorKey: "cycle" },
      { id: "wait", header: "Attente (min)", accessorKey: "wait" },
      { id: "tons", header: useApiMode ? "Tonnage" : "Tonnage est.", accessorKey: "tons" },
    ],
    rows,
    interpretation: {
      facts: [`${total} voyages sur le poste`, `Moyenne ${avg.toFixed(1)} / camion`],
      inference: useApiMode
        ? "Interprétation IA non activée — voyages issus des cycles complétés du poste."
        : "Les camions bloqués en file Banc B réalisent moins de rotations.",
      missing: useApiMode ? ["Moteur d'analyse Performance non activé"] : ["Répartition OD exacte par voyage"],
      confidence: useApiMode ? 0 : 82,
    },
  }
}

function buildDowntime(equipment: Equipment[], downtimeReasons: DowntimeReason[]): PerfAnalysis {
  const rows = downtimeReasons
    .map((d) => ({
      category: d.reason,
      duration: Number(d.hours.toFixed(1)),
      cause: d.reason.includes("non") || d.reason.toLowerCase().includes("indéfini") ? null : d.reason,
      status: useApiMode ? "—" : d.hours > 2 ? "Ouvert" : "Suivi",
      equipment: "—",
    }))
    .sort((a, b) => b.duration - a.duration)

  const spotlight = useApiMode ? [] : merahDowntimeSpotlightRows()

  const merged = [...spotlight, ...rows].slice(0, 12)
  const total = merged.reduce((s, r) => s + Number(r.duration), 0)
  const sansCause = merged.filter((r) => !r.cause).length

  return {
    metric: "downtime",
    title: performanceMetricLabel("downtime"),
    kpis: [
      { id: "total", label: "Cumul arrêts", value: `${total.toFixed(1)} h`, tone: "warn" },
      { id: "nocause", label: "Sans cause", value: String(sansCause), tone: sansCause > 0 ? "bad" : "good" },
      ...(useApiMode
        ? [{ id: "cats", label: "Catégories", value: String(merged.length) }]
        : merahDowntimeKpis()),
    ],
    chartKind: "stacked",
    chartData: merged.slice(0, 6).map((r) => ({
      name: String(r.category).slice(0, 18),
      duration: r.duration,
      withCause: r.cause ? r.duration : 0,
      noCause: r.cause ? 0 : r.duration,
    })),
    chartSeries: [
      { key: "withCause", name: "Avec cause", color: COLORS[0] },
      { key: "noCause", name: "Sans cause", color: COLORS[2] },
    ],
    columns: [
      { id: "category", header: "Catégorie", accessorKey: "category" },
      { id: "duration", header: "Durée (h)", accessorKey: "duration" },
      { id: "cause", header: "Cause", accessorKey: "cause" },
      { id: "status", header: "Statut", accessorKey: "status" },
      { id: "equipment", header: "Équipement", accessorKey: "equipment" },
    ],
    rows: merged.map((r) => ({ ...r, cause: r.cause ?? "—" })),
    interpretation: {
      facts: useApiMode
        ? [`${total.toFixed(1)} h d'arrêts`, `${sansCause} sans cause classée`]
        : merahDowntimeFacts(),
      inference: useApiMode
        ? "Interprétation IA non activée — arrêts dérivés des états / downtime_events."
        : "Les arrêts sans cause faussent le diagnostic et bloquent l'optimisation.",
      missing: useApiMode
        ? ["Moteur d'analyse Performance non activé"]
        : ["Taxonomie cause OPM complète", equipment.length ? "Lien Film ↔ motif" : "Motifs terrain"],
      confidence: useApiMode ? 0 : 85,
    },
  }
}

export const PERFORMANCE_METRICS: { id: PerformanceMetric; label: string }[] = [
  { id: "production", label: "Production" },
  { id: "cycle", label: "Cycle moyen" },
  { id: "waiting", label: "Temps d'attente" },
  { id: "fuel", label: "Consommation gasoil" },
  { id: "td", label: "Taux de disponibilité (TD)" },
  { id: "tu", label: "Taux d'utilisation (TU)" },
  { id: "downtime", label: "Arrêts" },
  { id: "voyages", label: "Voyages / rotations" },
]
