import type { Alert } from "@/lib/mock/types"
import type { JsonValue } from "@/lib/api/types/ai"
import type { RecommendationDecisionRecord } from "@/lib/api/types/actionsIa"

export type OptimizationOutcome =
  | "FEASIBLE"
  | "NO_FEASIBLE_PLAN"
  | "INSUFFICIENT_DATA"
  | "NOT_APPLICABLE"
  | "ERROR"

export type OptimizationCandidate = {
  candidateId: string
  truckId: number | null
  truckCode: string | null
  loaderId: number | null
  loaderCode: string | null
  destZoneCode: string | null
  originZoneCode: string | null
  roadIds: string[]
  distanceKm: number | null
  travelMinutes: number | null
  waitMinutes: number | null
  score: number | null
  constraintNotes: string[]
  isCurrent?: boolean
  rankReason: string
  rank?: number
}

export type OptimizationExplanation = {
  eligibility: string
  outcome: OptimizationOutcome | string
  optimizerVersion: string
  weights: { w_travel?: number; w_wait?: number }
  weatherStatus: string | null
  weatherScored: boolean
  recommendedCandidateId: string | null
  why: string
  missingReason?: string | null
}

export type OptimizationRun = {
  runId: string
  alertId: string
  siteId: number
  optimizerVersion: string
  weights: Record<string, number>
  eligibility: string
  outcome: OptimizationOutcome | string
  snapshotDigest: string | null
  candidates: OptimizationCandidate[]
  recommendedCandidateId: string | null
  weatherStatus: string | null
  createdAt: string | null
  explanation?: OptimizationExplanation | null
}

export type ActionsInboxItem = Alert & {
  hasInvestigation: boolean
  investigationId: string | null
  hasRecommendation: boolean
  optimizationEligible: boolean
  eligibility: string
  latestRunOutcome: string | null
  latestRunId: string | null
}

export type ActionsInboxPage = {
  items: ActionsInboxItem[]
  nextCursor: string | null
  hasMore: boolean
  activeCount: number
}

export type ActionsInboxDetail = {
  alert: ActionsInboxItem
  investigationId: string | null
  decision: RecommendationDecisionRecord | null
  latestRun: {
    runId: string
    outcome: string
    eligibility: string
    candidates: OptimizationCandidate[]
    recommendedCandidateId: string | null
    weatherStatus: string | null
    weights: Record<string, JsonValue>
    optimizerVersion: string
    createdAt: string | null
    explanation?: OptimizationExplanation | null
  } | null
}
