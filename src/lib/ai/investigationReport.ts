import type {
  EvidenceItem,
  Hypothesis,
  InvestigationResult,
  JsonValue,
} from "@/lib/api/types/ai"

export type EvidenceDirection = "up" | "down" | "stable" | "none"
export type EvidenceFamily = "electrical" | "thermal" | "oil" | "fuel" | "queue" | "production" | "connectivity" | "oem" | "timeline" | "other"
export type EvidenceRole = "observation" | "coverage"

export const PRIMARY_EVIDENCE_LIMIT = 3

const COVERAGE_METRICS = new Set([
  "fleet_snapshot",
  "completed_cycle_time_samples",
  "downtime_by_reason",
  "active_site_alerts",
  "equipment_state_timeline",
  "current_assignments",
  "operational_context",
  "equipment_timeline",
])

export type EvidenceSummary = {
  key: string
  evidenceId: string
  label: string
  value: string
  meaning: string | null
  why: string | null
  timestamp: string | null
  direction: EvidenceDirection
  available: boolean
  family: EvidenceFamily
  role: EvidenceRole
  sampleCount?: number | null
}

export type HypothesisRank = "BEST_SUPPORTED" | "CONTRADICTED" | "STRONG" | "MEDIUM" | "WEAK" | "ALTERNATIVE"

const METRIC_LABELS: Record<string, string> = {
  engine_temp_c: "Température moteur",
  coolant_temp_c: "Température liquide de refroidissement",
  oil_pressure_kpa: "Pression d’huile",
  fuel_rate_lph: "Débit carburant",
  fuel_level_pct: "Niveau carburant",
  engine_load_pct: "Charge moteur",
  speed_kmh: "Vitesse",
  payload_t: "Charge utile",
  battery_voltage: "Tension batterie",
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
  oem_diagnostic_parameters: "Paramètres de diagnostic OEM",
  oem_errors: "Alertes OEM",
  oem_error_codes: "Codes OEM",
  oem_connectivity: "Connectivité OEM",
  oem_maintenance_indicators: "Indicateurs de maintenance",
}

const FRENCH_BACKEND_MESSAGES: Record<string, string> = {
  "Available evidence is insufficient to determine a reliable root cause.":
    "Les preuves disponibles ne permettent pas d’identifier une cause racine fiable.",
  "Available evidence is insufficient to determine a reliable root cause. The observed operational condition requires further verification.":
    "Les preuves disponibles ne permettent pas d’identifier une cause racine fiable. La condition opérationnelle observée demande une vérification complémentaire.",
  "The exact causal mechanism or failed component is not confirmed.":
    "Le mécanisme causal exact ou le composant défaillant n’est pas confirmé.",
  "No evidence-backed hypothesis supports a probable cause.":
    "Aucune hypothèse étayée par les preuves ne permet d’établir une cause probable.",
  "Evidence cannot discriminate between competing hypotheses.":
    "Les preuves ne permettent pas de départager les hypothèses concurrentes.",
  "The proposed explanation restates the observed symptom without a deeper causal mechanism.":
    "L’explication proposée reformule le symptôme observé sans mécanisme causal plus profond.",
  "The diagnosis explicitly states that available evidence cannot support a conclusion.":
    "Le diagnostic indique que les preuves disponibles ne permettent pas de conclure.",
  "The maximum evidence-gathering iteration count was reached.":
    "Le nombre maximal de cycles de collecte de preuves a été atteint.",
  "No new supported evidence request remained available.":
    "Aucune nouvelle demande de preuve prise en charge n’était disponible.",
  "Available evidence cannot support a probable or confirmed cause.":
    "Les preuves disponibles ne permettent pas d’établir une cause probable ou confirmée.",
  "Verify the observed operational condition and collect the missing evidence before any intervention.":
    "Vérifier la condition opérationnelle observée et collecter les preuves manquantes avant toute intervention.",
  "This investigation did not establish a reliable root cause; human validation remains required.":
    "Cette investigation n’a pas établi de cause racine fiable ; la validation humaine reste requise.",
  "Verify the probable cause with an operator before any intervention.":
    "Vérifier la cause probable avec un opérateur avant toute intervention.",
  "The evidence supports a probable cause, but it is not confirmed; human validation remains required.":
    "Les preuves soutiennent une cause probable, mais elle n’est pas confirmée ; la validation humaine reste requise.",
}

const KNOWN_PREFIXES: Array<[string, string]> = [
  ["The available evidence supports the following as the best current explanation:", "Les preuves disponibles soutiennent actuellement :"],
  ["Authoritative evidence supports the following root cause:", "Les preuves font autorité pour la cause suivante :"],
]

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

function neutralizeSimulationWording(value: string): string {
  return value
    .replace(/sous seuil de simulation/gi, "sous le seuil attendu")
    .replace(/hors plage de simulation/gi, "hors de la plage attendue")
    .replace(/\s*\(simulation\)/gi, "")
}

export function operatorText(value: string): string {
  const trimmed = value.trim()
  const mapped = FRENCH_BACKEND_MESSAGES[trimmed]
  if (mapped) return mapped
  for (const [prefix, french] of KNOWN_PREFIXES) {
    if (trimmed.startsWith(prefix)) {
      const rest = trimmed.slice(prefix.length).trim()
      return rest ? `${french} ${rest}` : french
    }
  }
  return neutralizeSimulationWording(trimmed)
}

export function compactOperatorText(value: string, maxChars = 160): string {
  const text = operatorText(value).trim()
  const sentence = text.split(/(?<=[.!?…])\s+/)[0] ?? text
  if (sentence.length <= maxChars) return sentence
  return `${sentence.slice(0, maxChars - 1).trimEnd()}…`
}

export function uniqueDisplayStrings(values: string[]): string[] {
  const seen = new Set<string>()
  const unique: string[] = []
  for (const value of values) {
    const display = operatorText(value)
    const key = display.toLocaleLowerCase().replace(/[^\p{L}\p{N}]+/gu, " ").trim()
    if (!key || seen.has(key)) continue
    seen.add(key)
    unique.push(display)
  }
  return unique
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

const ELECTRICAL_RE = /batter|volt|électri|electri|alternat|sim-batt|charging|chargeur|syst[eè]me de charge|courant de charge|battery_voltage/

function familyFromText(text: string): EvidenceFamily {
  const value = text.toLowerCase()
  if (ELECTRICAL_RE.test(value)) return "electrical"
  if (/temp|therm|coolant|surchauff|refroid/.test(value)) return "thermal"
  if (/huile|oil.?press|lubr/.test(value)) return "oil"
  if (/fuel|carburant|consommation/.test(value)) return "fuel"
  if (/wait|attente|queue|congestion|chargement|loading/.test(value)) return "queue"
  if (/production|tonnage/.test(value)) return "production"
  if (/communication|connectivity|connexion/.test(value)) return "connectivity"
  if (/oem|error|diagnostic|sim-/.test(value)) return "oem"
  if (/timeline|état|state/.test(value)) return "timeline"
  return "other"
}

function diagnosisFamilies(result: InvestigationResult): Set<EvidenceFamily> {
  const text = [
    result.trigger.trigger_type,
    JSON.stringify(result.trigger.payload ?? {}),
    result.conclusion?.root_cause ?? "",
    result.conclusion?.observed_condition ?? "",
    result.conclusion?.summary ?? "",
    ...(result.conclusion?.contributing_factors.map((factor) => factor.statement) ?? []),
    ...result.hypotheses.map((hypothesis) => `${hypothesis.statement} ${hypothesis.rationale}`),
  ].join(" ")
  const families = new Set<EvidenceFamily>()
  const detected = familyFromText(text)
  if (detected !== "other") families.add(detected)
  if (ELECTRICAL_RE.test(text.toLowerCase())) families.add("electrical")
  if (/temp|therm|coolant|surchauff/.test(text.toLowerCase())) families.add("thermal")
  if (/huile|oil|lubr/.test(text.toLowerCase())) families.add("oil")
  if (/fuel|carburant/.test(text.toLowerCase())) families.add("fuel")
  if (families.has("thermal") || families.has("oil")) {
    families.add("thermal")
    families.add("oil")
  }
  return families
}

function isOemErrorEvidence(evidence: EvidenceItem): boolean {
  return /oem_error|error_code/.test(`${evidence.source_tool} ${evidence.metric}`)
}

function isDirectElectricalMeasurement(evidence: EvidenceItem): boolean {
  if (!evidence.available || evidence.value == null || isOemErrorEvidence(evidence)) return false
  const blob = `${evidence.metric} ${JSON.stringify(evidence.value)}`
  return ELECTRICAL_RE.test(blob.toLowerCase())
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
    const family = familyFromText(metric)
    return [{
      key: `${evidence.evidence_id}:trend:${metric}:${index}`,
      evidenceId: evidence.evidence_id,
      label: metricLabel(metric),
      value: `${formatNumber(first)} → ${formatNumber(last)}${unit ? ` ${unit}` : ""}`,
      meaning: direction.meaning ?? "Évolution mesurée",
      why: null,
      timestamp: stringValue(candidate.lastObservedAt) ?? evidence.observed_at,
      direction: direction.direction,
      available: true,
      family,
      role: "observation",
      sampleCount,
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
    why: null,
    timestamp: evidence.observed_at,
    direction: change === null ? "none" : change > 0 ? "up" : change < 0 ? "down" : "stable",
    available: waiting !== null || facts.length > 0,
    family: "queue",
    role: waiting !== null || facts.length > 0 ? "observation" : "coverage",
  }]
}

function oemSummaries(evidence: EvidenceItem): EvidenceSummary[] {
  const rows = Array.isArray(evidence.value)
    ? evidence.value.filter(isRecord)
    : isRecord(evidence.value) && (stringValue(evidence.value.errorCode) || stringValue(evidence.value.code))
      ? [evidence.value]
      : []
  const coded = rows.filter((row) => stringValue(row.errorCode) || (/^SIM-|^[A-Z0-9-]+$/.test(stringValue(row.code) ?? "") && stringValue(row.description)))
  if (!coded.length && typeof evidence.value === "string" && evidence.value.trim()) {
    const looksLikeCode = /SIM-|BATT|OEM|^[A-Z0-9-]{5,}$/i.test(evidence.value)
    return [{
      key: evidence.evidence_id,
      evidenceId: evidence.evidence_id,
      label: looksLikeCode ? "Code OEM" : "Alerte OEM",
      value: evidence.value,
      meaning: evidence.notes,
      why: "Confirme une anomalie détectée au moment de l’incident.",
      timestamp: evidence.observed_at,
      direction: "none",
      available: true,
      family: "oem",
      role: "observation",
    }]
  }
  return coded.slice(0, 4).map((row, index) => {
    const code = stringValue(row.errorCode) ?? stringValue(row.code) ?? "—"
    return {
      key: `${evidence.evidence_id}:oem:${index}`,
      evidenceId: evidence.evidence_id,
      label: "Code OEM",
      value: code,
      meaning: stringValue(row.description) ?? evidence.notes,
      why: "Confirme une anomalie détectée au moment de l’incident.",
      timestamp: stringValue(row.lastOccurrence) ?? stringValue(row.ts) ?? stringValue(row.firstOccurrence) ?? evidence.observed_at,
      direction: "none" as const,
      available: true,
      family: "oem" as const,
      role: "observation" as const,
    }
  })
}

function coverageCountLabel(metric: string): string | null {
  const labels: Record<string, string> = {
    fleet_snapshot: "équipements observés",
    completed_cycle_time_samples: "cycles terminés analysés",
    downtime_by_reason: "causes d’arrêt observées",
    active_site_alerts: "alertes actives",
    equipment_state_timeline: "segments d’état observés",
    current_assignments: "affectations actives",
  }
  return labels[metric] ?? null
}

function isCoverageMetric(metric: string): boolean {
  return COVERAGE_METRICS.has(metric)
}

function singleEvidenceSummary(evidence: EvidenceItem): EvidenceSummary {
  let value: string | null = null
  let meaning = evidence.notes
  let role: EvidenceRole = isCoverageMetric(evidence.metric) ? "coverage" : "observation"
  let sampleCount: number | null = null
  if (Array.isArray(evidence.value)) {
    const countLabel = coverageCountLabel(evidence.metric)
    if (countLabel) {
      sampleCount = evidence.value.length
      value = `${evidence.value.length} ${countLabel}`
      role = "coverage"
    }
  } else if (isRecord(evidence.value) && evidence.metric === "operational_context") {
    value = stringValue(evidence.value.siteName) ?? "Contexte du site récupéré"
    meaning = stringValue(evidence.value.shiftName) ?? meaning
    role = "coverage"
  } else if (isRecord(evidence.value) && (evidence.metric === "shift_production_summary" || evidence.metric === "shift_production" || evidence.metric === "production")) {
    const shiftly = evidence.value.shiftly
    const row = Array.isArray(shiftly) ? shiftly.find(isRecord) : null
    const tonnage = row ? numberValue(row.tonnage) : null
    const target = row ? numberValue(row.target) : null
    const attainment = row ? numberValue(row.attainmentPct) : null
    value = tonnage === null ? "Production non mesurée" : `${formatNumber(tonnage)} tonnes produites`
    meaning = target === null ? "Objectif non disponible" : `objectif ${formatNumber(target)} t${attainment === null ? "" : ` · atteinte ${formatNumber(attainment)} %`}`
    role = tonnage === null ? "coverage" : "observation"
  }
  const primitive = typeof evidence.value === "number" || typeof evidence.value === "string"
    ? `${String(evidence.value)}${evidence.unit ? ` ${evidence.unit}` : ""}`
    : value ?? "Données structurées disponibles"
  if (primitive === "Données structurées disponibles") role = "coverage"
  const family = /oem|error|diagnostic/.test(evidence.source_tool) || /oem/.test(evidence.metric)
    ? "oem"
    : /timeline|state/.test(evidence.metric)
      ? "timeline"
      : familyFromText(`${evidence.metric} ${evidence.source_tool}`)
  return {
    key: evidence.evidence_id,
    evidenceId: evidence.evidence_id,
    label: metricLabel(evidence.metric),
    value: evidence.available && evidence.value !== null ? primitive : "Indisponible",
    meaning,
    why: null,
    timestamp: evidence.observed_at,
    direction: "none",
    available: evidence.available && evidence.value !== null,
    family,
    role,
    sampleCount,
  }
}

export function summarizeEvidence(evidence: EvidenceItem): EvidenceSummary[] {
  if (!evidence.available || evidence.value === null) return [singleEvidenceSummary(evidence)]
  const oem = oemSummaries(evidence)
  if (oem.length) return oem
  if (isRecord(evidence.value)) {
    const trends = trendSummaries(evidence, evidence.value)
    if (trends.length) return trends
    const loading = loadingSummary(evidence, evidence.value)
    if (loading.length) return loading
  }
  return [singleEvidenceSummary(evidence)]
}

function topHypothesis(result: InvestigationResult): Hypothesis | undefined {
  const supported = result.conclusion?.supported_hypothesis_ids ?? []
  return result.hypotheses.find((hypothesis) => supported.includes(hypothesis.hypothesis_id))
    ?? result.hypotheses[0]
}

function annotateWhy(
  item: EvidenceSummary,
  topIds: Set<string>,
  families: Set<EvidenceFamily>,
): EvidenceSummary {
  if (item.family === "oem") {
    return {
      ...item,
      why: families.has("electrical")
        ? "Confirme une anomalie électrique détectée au moment de l’incident."
        : "Confirme une anomalie détectée au moment de l’incident.",
    }
  }
  if (item.why) return item
  if (!item.available) {
    return { ...item, why: "Cette mesure attendue n’est pas disponible dans les preuves collectées." }
  }
  if (topIds.has(item.evidenceId) && (item.direction === "down" || item.direction === "up")) {
    return { ...item, why: "Soutient une évolution pré-incident liée à l’hypothèse retenue." }
  }
  if (topIds.has(item.evidenceId)) {
    return { ...item, why: "Soutient l’hypothèse retenue." }
  }
  if ((families.has("electrical") || families.has("thermal")) && item.family === "timeline") {
    return { ...item, why: "Confirme le déroulement opérationnel de l’incident." }
  }
  return item
}

function missingElectricalCard(): EvidenceSummary {
  return {
    key: "missing-electrical",
    evidenceId: "",
    label: "Mesure électrique directe",
    value: "Indisponible",
    meaning: "Paramètres de diagnostic batterie/charge non disponibles",
    why: "Les paramètres de tension, courant de charge ou diagnostic batterie ne sont pas disponibles.",
    timestamp: null,
    direction: "none",
    available: false,
    family: "electrical",
    role: "observation",
  }
}

function matchesDiagnosisFamily(item: EvidenceSummary, families: Set<EvidenceFamily>): boolean {
  if (!families.size) return true
  return item.family === "oem" || item.family === "other" || families.has(item.family)
}

function rankScore(
  item: EvidenceSummary,
  families: Set<EvidenceFamily>,
  topIds: Set<string>,
  factIds: Set<string>,
  derivedIds: Set<string>,
  factorIds: Set<string>,
  recIds: Set<string>,
): number {
  let value = 0
  if (item.role === "observation") value += 100
  if (item.role === "coverage") value -= 40
  if (item.family === "oem") value += 90
  if (topIds.has(item.evidenceId)) value += 80
  if (factIds.has(item.evidenceId)) value += 40
  if (derivedIds.has(item.evidenceId)) value += 30
  if (factorIds.has(item.evidenceId)) value += 25
  if (recIds.has(item.evidenceId)) value += 10
  if (families.has(item.family)) value += 50
  if (item.available) value += 8
  if (item.direction !== "none") value += 4
  if (!item.available) value -= 80
  if (families.size && item.family !== "oem" && item.family !== "other" && !families.has(item.family)) value -= 60
  return value
}

function dedupeSummaries(items: EvidenceSummary[]): EvidenceSummary[] {
  const unique: EvidenceSummary[] = []
  for (const item of items) {
    if (unique.some((existing) => existing.label === item.label && existing.value === item.value)) continue
    unique.push(item)
  }
  return unique
}

export function rankEvidenceSummaries(result: InvestigationResult): EvidenceSummary[] {
  const families = diagnosisFamilies(result)
  const top = topHypothesis(result)
  const topIds = new Set(top?.supporting_evidence_ids ?? [])
  const factIds = new Set(result.conclusion?.observed_fact_evidence_ids ?? [])
  const derivedIds = new Set(result.conclusion?.derived_metric_evidence_ids ?? [])
  const factorIds = new Set(result.conclusion?.contributing_factors.flatMap((factor) => factor.evidence_ids) ?? [])
  const recIds = new Set(result.recommendation?.evidence_ids ?? [])
  const summaries = result.evidence.flatMap(summarizeEvidence)
  const electricalMissing = families.has("electrical")
    && !result.evidence.some(isDirectElectricalMeasurement)
    && !summaries.some((item) => item.available && item.family === "electrical")
  const ranked = (electricalMissing ? [...summaries, missingElectricalCard()] : summaries)
    .map((item) => annotateWhy(item, topIds, families))
    .sort((a, b) =>
      rankScore(b, families, topIds, factIds, derivedIds, factorIds, recIds)
      - rankScore(a, families, topIds, factIds, derivedIds, factorIds, recIds)
    )
  return dedupeSummaries(ranked)
}

export function partitionEvidence(result: InvestigationResult) {
  const all = rankEvidenceSummaries(result)
  const families = diagnosisFamilies(result)
  const availableObservations = all.filter((item) => item.available && item.role === "observation")
  const familyMatched = availableObservations.filter((item) => matchesDiagnosisFamily(item, families))
  const primaryPool = familyMatched.length
    ? familyMatched
    : availableObservations.length
      ? availableObservations
      : all.filter((item) => item.available)
  const primary = primaryPool.slice(0, PRIMARY_EVIDENCE_LIMIT)
  const overflow = primaryPool.slice(PRIMARY_EVIDENCE_LIMIT)
  const unavailable = all.filter((item) => !item.available)
  const coverage = all.filter((item) => item.role === "coverage")
  return { primary, overflow, unavailable, coverage, all }
}

export function keyEvidence(result: InvestigationResult, limit = PRIMARY_EVIDENCE_LIMIT): EvidenceSummary[] {
  return partitionEvidence(result).primary.slice(0, limit)
}

export function overflowEvidence(result: InvestigationResult): EvidenceSummary[] {
  return partitionEvidence(result).overflow
}

export function missingEvidence(result: InvestigationResult): EvidenceSummary[] {
  return partitionEvidence(result).unavailable
}

function normalizeForCompare(value: string): string {
  return operatorText(value).toLocaleLowerCase().replace(/[^\p{L}\p{N}]+/gu, " ").trim()
}

function canonicalTokens(value: string): Set<string> {
  const tokens = new Set<string>()
  for (const raw of normalizeForCompare(value).split(" ")) {
    if (raw.length < 4) continue
    if (/électri|electri|tension|volt|batter/.test(raw)) tokens.add("electrical")
    else if (/therm|temp|surchauff|refroid/.test(raw)) tokens.add("thermal")
    else tokens.add(raw)
  }
  return tokens
}

export function similarNarrative(left: string, right: string): boolean {
  const a = normalizeForCompare(left)
  const b = normalizeForCompare(right)
  if (!a || !b) return false
  if (a === b || a.includes(b) || b.includes(a)) return true
  const tokensA = canonicalTokens(left)
  const tokensB = canonicalTokens(right)
  if (!tokensA.size || !tokensB.size) return false
  const overlap = [...tokensA].filter((token) => tokensB.has(token)).length
  return overlap >= 2 && overlap / Math.min(tokensA.size, tokensB.size) >= 0.5
}

function isSymptomRestatement(mechanism: string, observed: string): boolean {
  if (similarNarrative(mechanism, observed)) return true
  const text = normalizeForCompare(mechanism)
  const hasComponent = /batter|alternat|charge|lubr|huile|refroid|pneu|tyre|moteur|loader|queue|réseau|gateway/.test(text)
  const hasSymptom = /tension|\bvolt|\btempérature|\btemperature\b|\barrêt|\barret\b|\bstop\b|attente|production|consommation/.test(text)
  return hasSymptom && !hasComponent
}

export function causalStorySteps(result: InvestigationResult): string[] {
  const conclusion = result.conclusion
  if (!conclusion) return []
  const observed = conclusion.observed_condition
    ? operatorText(conclusion.observed_condition)
    : "Condition opérationnelle signalée"
  const mechanism = conclusion.root_cause ? operatorText(conclusion.root_cause) : null
  const oem = rankEvidenceSummaries(result).find((item) => item.family === "oem" && item.available)
  const oemStep = oem?.available ? oem.value : null
  const distinctMechanism = Boolean(mechanism && !isSymptomRestatement(mechanism, observed))
  const depth = conclusion.causal_depth
  const steps: string[] = []
  if (oemStep) steps.push(oemStep)
  if (depth >= 1 && distinctMechanism && mechanism) steps.push(mechanism)
  if (!steps.some((step) => similarNarrative(step, observed))) steps.push(observed)
  if (depth < 1 || !distinctMechanism) {
    const unknown = "Le composant à l’origine de l’anomalie n’est pas identifié."
    if (!steps.includes(unknown)) steps.push(unknown)
  }
  return steps.slice(0, 4)
}

export function causalStoryIsUseful(result: InvestigationResult): boolean {
  const conclusion = result.conclusion
  if (!conclusion) return false
  const steps = causalStorySteps(result)
  if (steps.length < 2) return false
  const oem = rankEvidenceSummaries(result).find((item) => item.family === "oem" && item.available)
  if (oem && steps.some((step) => step === oem.value || step.includes(oem.value))) return true
  const incident = conclusion.observed_condition ? operatorText(conclusion.observed_condition) : ""
  const cause = conclusion.root_cause ? operatorText(conclusion.root_cause) : ""
  return steps.some((step) =>
    (!incident || !similarNarrative(step, incident))
    && (!cause || !similarNarrative(step, cause))
  )
}

export function hypothesisRank(
  hypothesis: Hypothesis,
  result: InvestigationResult,
  index: number,
): HypothesisRank {
  if (hypothesis.contradictory_evidence_ids.length) return "CONTRADICTED"
  if (index === 0 && result.conclusion?.supported_hypothesis_ids.includes(hypothesis.hypothesis_id)) {
    return "BEST_SUPPORTED"
  }
  if (hypothesis.supporting_evidence_ids.length === 0 || hypothesis.confidence === "LOW") return "WEAK"
  if (hypothesis.confidence === "HIGH") return "STRONG"
  if (hypothesis.confidence === "MEDIUM") return "MEDIUM"
  return "ALTERNATIVE"
}
