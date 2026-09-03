import type { Alert } from "@/lib/mock/types"
import type { RecommendationDecisionRecord } from "@/lib/api/types/actionsIa"

export type OptimizationOutcome =
  | "FEASIBLE"
  | "NO_FEASIBLE_PLAN"
  | "INSUFFICIENT_DATA"
  | "NOT_APPLICABLE"
  | "NOT_APPLICABLE_TO_DISPATCH"
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
  candidateRelation?: "BASELINE" | "IMPROVEMENT" | "EQUIVALENT" | "TRADEOFF"
  equivalentGroupId?: string | null
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

export type OptimizationWorkflowStatus =
  | "ORCHESTRATED"
  | "DETERMINISTIC_ONLY"
  | "REVIEW_UNAVAILABLE"
  | "NO_CHANGE_RECOMMENDED"
  | "INSUFFICIENT_EVIDENCE"

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
  workflowStatus?: OptimizationWorkflowStatus | string | null
  reviewStatus?: string | null
  displayedCandidateIds?: string[] | null
  baselineCandidateId?: string | null
  reviewerCaution?: string | null
  operatorSummary?: string | null
  operatorRecommendedAction?: { text: string | null; source: string | null } | null
  deterministicOnly?: boolean
  reviewUnavailable?: boolean
  reoptimizationOccurred?: boolean
  optimizationPassCount?: number | null
  pipelineStages?: string[] | null
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
  latestRun: OptimizationRun | null
}
