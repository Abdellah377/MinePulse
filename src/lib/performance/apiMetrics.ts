/** Presentation of server-defined values. No fleet ratios, queue inference or AI heuristics. */
import type { Equipment, Zone, DowntimeReason, ProductionRecord } from "@/lib/mock/types"
import type { PerformanceMetric } from "@/lib/workspace/types"
import type { PerfAnalysis, PerfColumn } from "@/lib/performance/metrics"
import { performanceMetricLabel } from "@/lib/workspace/titles"

const columns = (pairs: Array<[string, string]>): PerfColumn[] => pairs.map(([id, header]) => ({ id, header, accessorKey: id }))

export function buildApiPerformance(input: {
  metric: PerformanceMetric; equipment: Equipment[]; zones: Zone[]; downtimeReasons: DowntimeReason[]
  fuelMode?: "lph" | "lpt" | "idle"
  productionShiftly?: ProductionRecord[]
}): PerfAnalysis {
  const { metric, equipment, zones, downtimeReasons } = input
  const trucks = equipment.filter((e) => e.type === "haul_truck")
  const analysis: PerfAnalysis = {
    metric, title: performanceMetricLabel(metric), kpis: [], chartKind: "bar", chartData: [], chartSeries: [], columns: [], rows: [],
    interpretation: { facts: ["Valeurs fournies par les services opérationnels pour le poste sélectionné."], inference: "Non évalué — consulter Alertes IA pour une investigation.", missing: [], confidence: null },
  }
  const unavailable = (id: string, label: string) => ({ id, label, value: "—", hint: "Agrégat non fourni par le backend" })
  if (metric === "fuel") {
    const mode = input.fuelMode ?? "lph"
    analysis.fuelMode = mode
    analysis.kpis = [unavailable("total", "Litres poste"), unavailable("avg", "Moy. flotte l/h"), unavailable("idle", "Idle L")]
    analysis.rows = equipment.map((e) => ({ code: e.code, lph: e.gasoilLph, litres: null, lpt: null, idleL: null }))
    analysis.columns = columns([["code", "Équipement"], ["lph", "Débit mesuré (l/h)"], ["litres", "Litres poste"], ["lpt", "L/t"], ["idleL", "Idle L"]])
    const key = mode === "idle" ? "idleL" : mode
    analysis.chartData = analysis.rows.map((r) => ({ name: r.code, [key]: r[key] }))
    analysis.chartSeries = [{ key, name: mode === "lph" ? "l/h mesuré" : mode === "lpt" ? "L/t — non évalué" : "Idle L — non évalué" }]
    analysis.interpretation.missing = ["Consommation intégrée sur le poste, L/t et consommation au ralenti non fournis."]
  } else if (metric === "cycle") {
    const target = input.productionShiftly?.[0]?.targetCycleMin
    analysis.kpis = [unavailable("avg", "Cycle moy. flotte"), { id: "target", label: "Cible cycle poste", value: target == null ? "—" : `${target} min` }, unavailable("trips", "Agrégat cycles")]
    analysis.rows = trucks.map((e) => ({ code: e.code, cycles: e.tripsThisShift, avg: e.cycleDureeMoyenneMin }))
    analysis.columns = columns([["code", "Équipement"], ["cycles", "Cycles complétés"], ["avg", "Cycle moyen (min)"]])
    analysis.chartData = analysis.rows.map((r) => ({ name: r.code, avg: r.avg }))
    analysis.chartSeries = [{ key: "avg", name: "Cycle moyen par engin (min)" }]
    analysis.interpretation.missing = ["Moyenne flotte pondérée et décomposition agrégée non exposées. Une étape manquante ne vaut pas zéro."]
  } else if (metric === "waiting") {
    analysis.kpis = [unavailable("avg", "Attente moy. zone"), unavailable("bancb", "File max"), unavailable("lost", "Temps perdu")]
    analysis.rows = zones.map((z) => ({ zone: z.name, trucks: trucks.filter((e) => e.zoneId === z.id).length, avgQueue: null, maxQueue: null, waitMin: null, lostTime: null }))
    analysis.columns = columns([["zone", "Zone"], ["trucks", "Camions actuellement localisés"], ["avgQueue", "File moyenne"], ["maxQueue", "File max"], ["waitMin", "Attente zone (min)"]])
    // Current inventory grouping is not a historical queue metric.
    analysis.chartData = trucks.map((e) => ({ name: e.code, wait: e.waitingMinutesThisShift }))
    analysis.chartSeries = [{ key: "wait", name: "Attente cumulée poste par engin (min)" }]
    analysis.interpretation.missing = ["Historique des files et attente attribuée à chaque zone non exposés. La position actuelle ne localise pas les attentes passées."]
  } else if (metric === "td" || metric === "tu") {
    analysis.kpis = [unavailable(metric, `${metric.toUpperCase()} flotte`)]
    analysis.rows = equipment.map((e) => ({ code: e.code, [metric]: metric === "td" ? e.tdPct : e.tuPct }))
    analysis.columns = columns([["code", "Équipement"], [metric, `${metric.toUpperCase()} % (backend)`]])
    analysis.chartData = analysis.rows.map((r) => ({ name: r.code, [metric]: r[metric] }))
    analysis.chartSeries = [{ key: metric, name: `${metric.toUpperCase()} % par engin` }]
    analysis.interpretation.missing = ["Agrégat flotte pondéré non exposé. Les pourcentages individuels ne sont pas moyennés localement."]
  } else if (metric === "voyages") {
    analysis.kpis = [unavailable("total", "Agrégat voyages"), unavailable("avg", "Moy. / camion"), unavailable("tons", "Tonnage / engin")]
    analysis.rows = trucks.map((e) => ({ code: e.code, trips: e.tripsThisShift, wait: e.waitingMinutesThisShift, cycle: e.cycleDureeMoyenneMin, tons: null }))
    analysis.columns = columns([["code", "Équipement"], ["trips", "Voyages"], ["cycle", "Cycle moyen (min)"], ["wait", "Attente cumulée (min)"], ["tons", "Tonnage"]])
    analysis.chartData = analysis.rows.map((r) => ({ name: r.code, trips: r.trips }))
    analysis.chartSeries = [{ key: "trips", name: "Cycles complétés" }]
    analysis.interpretation.missing = ["Tonnage par engin non exposé ; le chargement instantané ne représente pas le tonnage transporté."]
  } else if (metric === "downtime") {
    analysis.kpis = [unavailable("total", "Agrégat arrêts"), unavailable("nocause", "Sans cause")]
    analysis.rows = downtimeReasons.map((d) => ({ category: d.reason, duration: d.hours, cause: null, status: "—", equipment: "—" }))
    analysis.columns = columns([["category", "Catégorie"], ["duration", "Durée (h)"], ["cause", "Cause validée"], ["status", "Statut"]])
    analysis.chartData = analysis.rows.map((r) => ({ name: r.category, duration: r.duration }))
    analysis.chartSeries = [{ key: "duration", name: "Durée par catégorie (h)" }]
    analysis.interpretation.missing = ["Cause validée et lien événement/engin non exposés dans cet agrégat."]
  }
  return analysis
}
