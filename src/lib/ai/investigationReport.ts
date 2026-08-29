import type {
  EvidenceItem,
  Hypothesis,
  InvestigationResult,
  JsonValue,
} from "@/lib/api/types/ai"

export type EvidenceDirection = "up" | "down" | "stable" | "none"

export type EvidenceSummary = {
  key: string
  evidenceId: string
  label: string
  value: string
  meaning: string | null
  timestamp: string | null
  direction: EvidenceDirection
  available: boolean
}

const METRIC_LABELS: Record<string, string> = {
  engine_temp_c: "Température moteur",
  coolant_temp_c: "Température liquide de refroidissement",
  oil_pressure_kpa: "Pression d’huile",
  fuel_rate_lph: "Débit carburant",
  fuel_level_pct: "Niveau carburant",
  engine_load_pct: "Charge moteur",
  speed_kmh: "Vitesse",
  payload_t: "Charge utile",
  communication_quality: "Qualité de communication",
  operational_context: "Contexte opérationnel",
  equipment_telemetry_trends: "Tendances télémétriques",
  loading_queue_and_service_context: "Contexte chargement et file d’attente",
  equipment_timeline: "Historique d’état équipement",
  shift_production: "Production du poste",
  production: "Production du poste",
  shift_production_summary: "Production du poste",
  fleet_snapshot: "État de la flotte",
  completed_cycle_time_samples: "Cycles terminés",
  downtime_by_reason: "Arrêts par cause",
  active_site_alerts: "Alertes actives",
  equipment_state_timeline: "Historique d’état équipement",
  cycle_performance: "Performance des cycles",
  downtime: "Temps d’arrêt",
  site_alerts: "Alertes opérationnelles",
  oem_diagnostics: "Diagnostic OEM",
  oem_errors: "Alertes OEM",
  oem_connectivity: "Connectivité OEM",
  oem_maintenance_indicators: "Indicateurs de maintenance",
}

const FRENCH_BACKEND_MESSAGES: Record<string, string> = {
  "Available evidence is insufficient to determine a reliable root cause.":
    "Les preuves disponibles ne permettent pas d’identifier une cause racine fiable.",
  "The exact causal mechanism or failed component is not confirmed.":
    "Le mécanisme causal exact ou le composant défaillant n’est pas confirmé.",
  "No evidence-backed hypothesis supports a probable cause.":
    "Aucune hypothèse étayée par les preuves ne permet d’établir une cause probable.",
  "Evidence cannot discriminate between competing hypotheses.":
    "Les preuves ne permettent pas de départager les hypothèses concurrentes.",
}

function isRecord(value: JsonValue | undefined): value is { [key: string]: JsonValue } {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

function numberValue(value: JsonValue | undefined): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null
}

function stringValue(value: JsonValue | undefined): string | null {
  return typeof value === "string" && value.trim() ? value : null
}

function formatNumber(value: number): string {
  return new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 2 }).format(value)
}

export function operatorText(value: string): string {
  return FRENCH_BACKEND_MESSAGES[value.trim()] ?? value
}

export function formatInvestigationTime(value: string | null | undefined): string {
  if (!value) return "Horodatage indisponible"
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return "Horodatage indisponible"
  return date.toLocaleString("fr-FR", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  })
}

export function metricLabel(metric: string): string {
  return METRIC_LABELS[metric] ?? metric
    .replace(/_/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase())
}

function directionPresentation(value: JsonValue | undefined): {
  direction: EvidenceDirection
  meaning: string | null
} {
  if (value === "rising") return { direction: "up", meaning: "Tendance en hausse" }
  if (value === "falling") return { direction: "down", meaning: "Tendance en baisse" }
  if (value === "stable") return { direction: "stable", meaning: "Tendance stable" }
  return { direction: "none", meaning: null }
}

function trendSummaries(evidence: EvidenceItem, value: { [key: string]: JsonValue }): EvidenceSummary[] {
  const metrics = value.metrics
  if (!Array.isArray(metrics)) return []
  return metrics.flatMap((candidate, index) => {
    if (!isRecord(candidate) || numberValue(candidate.sampleCount) === null) return []
    const sampleCount = numberValue(candidate.sampleCount) ?? 0
    const first = numberValue(candidate.firstValue)
    const last = numberValue(candidate.lastValue)
    if (sampleCount === 0 || first === null || last === null) return []
    const metric = stringValue(candidate.metric) ?? evidence.metric
    const unit = stringValue(candidate.unit) ?? evidence.unit
    const direction = directionPresentation(candidate.direction)
    return [{
      key: `${evidence.evidence_id}:trend:${metric}:${index}`,
      evidenceId: evidence.evidence_id,
      label: metricLabel(metric),
      value: `${formatNumber(first)} → ${formatNumber(last)}${unit ? ` ${unit}` : ""}`,
      meaning: `${direction.meaning ?? "Évolution mesurée"} · ${sampleCount} mesures`,
      timestamp: stringValue(candidate.lastObservedAt) ?? evidence.observed_at,
      direction: direction.direction,
      available: true,
    }]
  })
}

function loadingSummary(evidence: EvidenceItem, value: { [key: string]: JsonValue }): EvidenceSummary[] {
  if (!Array.isArray(value.loaders)) return []
  const loader = value.loaders.find(isRecord)
  if (!loader) return []
  const code = stringValue(loader.loaderCode)
  const waiting = numberValue(loader.waitingTruckCount)
  const recent = numberValue(loader.recentAverageLoadingMinutes)
  const baseline = numberValue(loader.baselineAverageLoadingMinutes)
  const change = numberValue(loader.loadingDurationChangePct)
  const facts = [
    recent !== null ? `service récent ${formatNumber(recent)} min` : null,
    baseline !== null ? `référence ${formatNumber(baseline)} min` : null,
    change !== null ? `écart ${change > 0 ? "+" : ""}${formatNumber(change)} %` : null,
  ].filter((item): item is string => item !== null)
  return [{
    key: `${evidence.evidence_id}:loading`,
    evidenceId: evidence.evidence_id,
    label: code ? `Point de chargement · ${code}` : metricLabel(evidence.metric),
    value: waiting === null ? "File d’attente non mesurée" : `${waiting} camion${waiting === 1 ? "" : "s"} en attente`,
    meaning: facts.length ? facts.join(" · ") : evidence.notes,
    timestamp: evidence.observed_at,
    direction: change === null ? "none" : change > 0 ? "up" : change < 0 ? "down" : "stable",
    available: true,
  }]
}

function singleEvidenceSummary(evidence: EvidenceItem): EvidenceSummary {
  let value: string | null = null
  let meaning = evidence.notes
  if (Array.isArray(evidence.value)) {
    const countLabel: Record<string, string> = {
      fleet_snapshot: "équipements observés",
      completed_cycle_time_samples: "cycles terminés analysés",
      downtime_by_reason: "causes d’arrêt observées",
      active_site_alerts: "alertes actives",
      equipment_state_timeline: "segments d’état observés",
      current_assignments: "affectations actives",
    }
    value = countLabel[evidence.metric] ? `${evidence.value.length} ${countLabel[evidence.metric]}` : null
  } else if (isRecord(evidence.value) && evidence.metric === "operational_context") {
    value = stringValue(evidence.value.siteName) ?? "Contexte du site récupéré"
    meaning = stringValue(evidence.value.shiftName) ?? meaning
  } else if (isRecord(evidence.value) && evidence.metric === "shift_production_summary") {
    const shiftly = evidence.value.shiftly
    const row = Array.isArray(shiftly) ? shiftly.find(isRecord) : null
    const tonnage = row ? numberValue(row.tonnage) : null
    const target = row ? numberValue(row.target) : null
    const attainment = row ? numberValue(row.attainmentPct) : null
    value = tonnage === null ? "Production non mesurée" : `${formatNumber(tonnage)} tonnes produites`
    meaning = target === null ? "Objectif non disponible" : `objectif ${formatNumber(target)} t${attainment === null ? "" : ` · atteinte ${formatNumber(attainment)} %`}`
  }
  const primitive = typeof evidence.value === "number" || typeof evidence.value === "string"
    ? `${String(evidence.value)}${evidence.unit ? ` ${evidence.unit}` : ""}`
    : value ?? "Données structurées disponibles"
  return {
    key: evidence.evidence_id,
    evidenceId: evidence.evidence_id,
    label: metricLabel(evidence.metric),
    value: evidence.available && evidence.value !== null ? primitive : "Indisponible",
    meaning,
    timestamp: evidence.observed_at,
    direction: "none",
    available: evidence.available && evidence.value !== null,
  }
}

export function summarizeEvidence(evidence: EvidenceItem): EvidenceSummary[] {
  if (!evidence.available || evidence.value === null) return [singleEvidenceSummary(evidence)]
  if (isRecord(evidence.value)) {
    const trends = trendSummaries(evidence, evidence.value)
    if (trends.length) return trends
    const loading = loadingSummary(evidence, evidence.value)
    if (loading.length) return loading
  }
  return [singleEvidenceSummary(evidence)]
}

function referencedEvidenceIds(result: InvestigationResult): string[] {
  const conclusion = result.conclusion
  const supportedHypotheses = result.hypotheses.filter((hypothesis) =>
    conclusion?.supported_hypothesis_ids.includes(hypothesis.hypothesis_id),
  )
  return [
    ...supportedHypotheses.flatMap((hypothesis) => hypothesis.supporting_evidence_ids),
    ...(conclusion?.observed_fact_evidence_ids ?? []),
    ...(conclusion?.derived_metric_evidence_ids ?? []),
    ...(result.recommendation?.evidence_ids ?? []),
    ...result.evidence.filter((evidence) => evidence.available).map((evidence) => evidence.evidence_id),
  ].filter((id, index, ids) => ids.indexOf(id) === index)
}

export function keyEvidence(result: InvestigationResult, limit = 5): EvidenceSummary[] {
  const byId = new Map(result.evidence.map((evidence) => [evidence.evidence_id, evidence]))
  const triggerText = `${result.trigger.trigger_type} ${JSON.stringify(result.trigger.payload)}`.toLowerCase()
  const relevance = (evidenceId: string): number => {
    const metric = byId.get(evidenceId)?.metric ?? ""
    if (result.trigger.trigger_type === "CONGESTION_RISK" || /wait|attente|congestion|cycle/.test(triggerText)) {
      if (/loading_queue|loading_context/.test(metric)) return 30
      if (/cycle|timeline/.test(metric)) return 20
      if (/fleet|assignment/.test(metric)) return 12
      if (/telemetry/.test(metric)) return -10
    }
    if (result.trigger.trigger_type === "PRODUCTION_DEVIATION") {
      if (/production/.test(metric)) return 30
      if (/cycle|loading|fleet|downtime/.test(metric)) return 20
    }
    if (result.trigger.trigger_type === "CONNECTIVITY_ISSUE" || /communication|connectivity/.test(triggerText)) {
      if (/connectivity|communication/.test(metric)) return 30
      if (/telemetry|timeline/.test(metric)) return 20
    }
    if (/fuel|carburant|consommation/.test(triggerText)) {
      if (/telemetry/.test(metric)) return 30
      if (/cycle|production|fleet/.test(metric)) return 15
    }
    if (result.trigger.trigger_type === "EQUIPMENT_ANOMALY" || result.trigger.trigger_type === "MAINTENANCE_RISK") {
      if (/telemetry|diagnostic|maintenance|oem|timeline/.test(metric)) return 25
    }
    return 0
  }
  const summaries: EvidenceSummary[] = []
  for (const evidenceId of referencedEvidenceIds(result)) {
    const evidence = byId.get(evidenceId)
    if (!evidence) continue
    summaries.push(...summarizeEvidence(evidence))
  }
  return summaries
    .sort((a, b) => {
      const score = (item: EvidenceSummary) =>
        relevance(item.evidenceId) +
        (item.available ? 10 : 0) +
        (item.direction !== "none" ? 4 : 0) +
        (item.value !== "Données structurées disponibles" ? 3 : 0) +
        (item.meaning ? 1 : 0)
      return score(b) - score(a)
    })
    .filter((item, _index, items) => item.available || !items.some((candidate) => candidate.available))
    .slice(0, limit)
}

export function hypothesisRank(
  hypothesis: Hypothesis,
  result: InvestigationResult,
  index: number,
): "BEST_SUPPORTED" | "CONTRADICTED" | "WEAK" | "ALTERNATIVE" {
  if (hypothesis.contradictory_evidence_ids.length) return "CONTRADICTED"
  if (index === 0 && result.conclusion?.supported_hypothesis_ids.includes(hypothesis.hypothesis_id)) {
    return "BEST_SUPPORTED"
  }
  if (hypothesis.confidence === "LOW" || hypothesis.supporting_evidence_ids.length === 0) return "WEAK"
  return "ALTERNATIVE"
}
