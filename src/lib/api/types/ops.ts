/** Mirrors backend operational API contracts. */

export type CycleStageDto = {
  key: string
  minutes: number | null
  isCurrent: boolean
  isOutlier: boolean
}

export type EquipmentLiveDto = {
  id: string
  code: string
  type: string
  model: string
  state: string
  position: { x: number; y: number } | null
  heading: number | null
  speedKmh: number | null
  fuelPct: number | null
  gasoilLph: number | null
  tdPct: number | null
  tuPct: number | null
  engineOn: boolean | null
  operatorId: string | null
  zoneId: string | null
  destinationZoneId: string | null
  payloadTons: number | null
  capacityTons: number | null
  odometerKm: number | null
  engineHours: number | null
  tripsThisShift: number
  waitingMinutesThisShift: number
  idleMinutesThisShift: number
  lastUpdate: number | null
  siteId: string
  healthScore: number | null
  cycleActuel: CycleStageDto[]
  cycleDureeMoyenneMin: number | null
}

export type FailureRiskStatus = "AVAILABLE" | "INSUFFICIENT_HISTORY" | "UNAVAILABLE"

export type FailureRiskLevel = "LOW" | "MEDIUM" | "HIGH"

export type FailureRiskDto = {
  equipmentId: number | null
  equipmentCode: string | null
  predictionTimestamp: string | null
  horizonMinutes: number
  riskProbability: number | null
  riskLevel: FailureRiskLevel | null
  modelVersion: string
  modelType: string | null
  servedPredictor: string | null
  threshold: number | null
  status: FailureRiskStatus
  dataClass: string
  topPredictiveSignals: string[]
  detail: string | null
}

export type ProductionRecordDto = {
  label: string
  tonnage: number
  target: number | null
  targetCycleMin?: number | null
}

export type ProductionSummaryDto = {
  hourly: ProductionRecordDto[]
  daily: ProductionRecordDto[]
  shiftly: ProductionRecordDto[]
}

export type AlertDto = {
  id: string
  severity: string
  status: string
  title: string
  description: string
  equipmentId: string | null
  zoneId: string | null
  location: string
  category: string
  occurredAt: number
  createdAt: number
  updatedAt: number
  assignedTo: string | null
  resolution: string | null
}
