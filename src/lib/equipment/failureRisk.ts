import type { FailureRiskDto, FailureRiskLevel } from "@/lib/api/types/ops"

export const FAILURE_RISK_WINDOW_COPY =
  "Probabilité prédite d'un arrêt mécanique dans les 60 prochaines minutes."

export const FAILURE_RISK_PROTOTYPE_LABEL = "Prédiction prototype"

export const FAILURE_RISK_PROTOTYPE_WARNING =
  "Modèle entraîné sur des données synthétiques du simulateur MinePulse ; non validé sur le terrain."

export const RISK_LEVEL_LABEL: Record<FailureRiskLevel, string> = {
  LOW: "Faible",
  MEDIUM: "Moyen",
  HIGH: "Élevé",
}

const SIGNAL_LABELS: Record<string, string> = {
  engine_temp_c: "Température moteur",
  coolant_temp_c: "Température du liquide de refroidissement",
  oil_pressure_kpa: "Pression d'huile",
  battery_voltage: "Tension batterie",
  engine_rpm: "Régime moteur",
  engine_load_pct: "Charge moteur",
  fuel_rate_lph: "Consommation carburant",
}

export function formatFailureRiskPercent(probability: number): string {
  return `${Math.round(probability * 100)}%`
}

export function signalLabel(name: string): string {
  return SIGNAL_LABELS[name] ?? name.replaceAll("_", " ")
}

function hashSeed(id: string) {
  let h = 0
  for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) >>> 0
  return h
}

/** Demo-mode only. Never used when VITE_USE_API is true. */
export function demoFailureRisk(equipmentId: string): FailureRiskDto {
  const seed = hashSeed(equipmentId)
  const canned: Array<{ riskProbability: number; riskLevel: FailureRiskLevel }> = [
    { riskProbability: 0.22, riskLevel: "LOW" },
    { riskProbability: 0.45, riskLevel: "MEDIUM" },
    { riskProbability: 0.74, riskLevel: "HIGH" },
  ]
  const picked = canned[seed % canned.length]
  return {
    equipmentId: null,
    equipmentCode: equipmentId,
    predictionTimestamp: null,
    horizonMinutes: 60,
    riskProbability: picked.riskProbability,
    riskLevel: picked.riskLevel,
    modelVersion: "failure_risk_v1",
    modelType: "logistic",
    servedPredictor: "logistic",
    threshold: null,
    status: "AVAILABLE",
    dataClass: "synthetic_prototype",
    topPredictiveSignals: ["engine_temp_c", "oil_pressure_kpa"],
    detail: null,
  }
}
