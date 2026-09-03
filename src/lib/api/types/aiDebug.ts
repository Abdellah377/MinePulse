/** Developer-only investigation debug trace. Kept out of the operator InvestigationResult contract. */

export type DebugEventType =
  | "INVESTIGATION_STARTED"
  | "CONTEXT_RESOLVED"
  | "INITIAL_EVIDENCE_GATHERED"
  | "TOOL_COMPLETED"
  | "LLM_CALL"
  | "LLM_ATTEMPT"
  | "NODE_TIMING"
  | "ADDITIONAL_EVIDENCE_REQUESTED"
  | "ROUTER_DECISION"
  | "HYPOTHESIS_EVALUATED"
  | "VALIDATION_CHECK"
  | "STATUS_DOWNGRADED"
  | "CONCLUSION_BUILT"
  | "RECOMMENDATION_BUILT"
  | "PROVIDER_FAILURE"
  | "INVESTIGATION_COMPLETED"
  | "INVESTIGATION_FAILED"

export type InvestigationStopReason =
  | "CONFIRMED_CAUSE"
  | "PROBABLE_CAUSE"
  | "EVIDENCE_EXHAUSTED"
  | "MAX_ITERATIONS"
  | "NO_DOMINANT_HYPOTHESIS"
  | "PROVIDER_FAILURE"
  | "TOOL_FAILURE"
  | "INCONCLUSIVE_AFTER_VALIDATION"

export interface DebugEvent {
  event_id: string
  sequence: number
  timestamp: string
  stage: string
  event_type: DebugEventType
  summary: string
  duration_ms: number | null
  metadata: Record<string, unknown>
}

export interface ValidationCheck {
  check_id: string
  passed: boolean
  detail: string
}

export interface EvidenceCoverage {
  initial_count: number
  additional_requested: number
  available: number
  unavailable: number
  contradictory: number
  iterations: number
  max_iterations: number
  families: string[]
}

export interface DebugUsage {
  model: string | null
  request_count: number
  input_tokens: number | null
  output_tokens: number | null
  total_tokens: number | null
}

export interface DebugDurations {
  total: number | null
  llm: number
  evidence: number
  persist?: number
  nodes?: Record<string, number>
}

export interface CompactConclusion {
  diagnosis_status: string | null
  root_cause: string | null
  reliable_root_cause: boolean | null
  confidence: string | null
  supported_hypothesis_ids: string[]
}

export interface InvestigationDebugTrace {
  investigation_id: string
  graph_version: string | null
  provider: string | null
  model: string | null
  stop_reason: InvestigationStopReason | null
  events: DebugEvent[]
  llm_proposed: CompactConclusion | null
  backend_enforced: CompactConclusion | null
  validation_checks: ValidationCheck[]
  coverage: EvidenceCoverage
  usage: DebugUsage
  wall_durations_ms: DebugDurations
  trigger: Record<string, unknown>
  recommendation: Record<string, unknown>
  error: Record<string, unknown> | null
}
