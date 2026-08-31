import type { InvestigationRecommendation, JsonValue } from "@/lib/api/types/ai"

export type RecommendationDecisionType = "PENDING" | "ACCEPTED" | "MODIFIED" | "REJECTED"

export type FollowUpStatus = "OPEN" | "RESOLVED"

export type RejectionReasonCategory =
  | "IMPOSSIBLE_OPERATIONNELLEMENT"
  | "CONTRAINTE_NON_CONNUE_PAR_IA"
  | "RISQUE_SECURITE"
  | "MAUVAISE_PRIORITE_PRODUCTION"
  | "INFORMATION_INCORRECTE"
  | "MEILLEURE_ALTERNATIVE"
  | "AUTRE"

export type DiscussionRole = "OPERATOR" | "ASSISTANT"

export type RecommendationDecisionRecord = {
  decision_id: string
  investigation_id: string
  site_id: number
  decision_type: RecommendationDecisionType
  follow_up_status: FollowUpStatus
  reason_category: RejectionReasonCategory | null
  reason_text: string | null
  alternative_action: string | null
  original_recommendation: InvestigationRecommendation | Record<string, JsonValue>
  operator_action: Record<string, JsonValue> | null
  actor_label: string | null
  context_tags: Record<string, JsonValue>
  outcome_status: string | null
  outcome_notes: string | null
  created_at: string
  updated_at: string
}

export type RecommendationDecisionView = {
  investigation_id: string
  decision_type: RecommendationDecisionType
  follow_up_status: FollowUpStatus | null
  decision: RecommendationDecisionRecord | null
}

export type RecommendationDecisionRequest = {
  decision_type: Exclude<RecommendationDecisionType, "PENDING">
  reason_category?: RejectionReasonCategory | null
  reason_text?: string | null
  alternative_action?: string | null
  actor_label?: string | null
}

export type FollowUpStatusRequest = {
  follow_up_status: FollowUpStatus
}

export type DiscussionMessageRecord = {
  message_id: string
  investigation_id: string
  role: DiscussionRole
  content: string
  actor_label: string | null
  cited_evidence_ids: Array<string>
  created_at: string
}

export type DiscussionThread = {
  investigation_id: string
  messages: Array<DiscussionMessageRecord>
}

export type DiscussionPostRequest = {
  content: string
  actor_label?: string | null
  generate_reply?: boolean
}

export const REJECTION_REASON_LABEL: Record<RejectionReasonCategory, string> = {
  IMPOSSIBLE_OPERATIONNELLEMENT: "Impossible opérationnellement",
  CONTRAINTE_NON_CONNUE_PAR_IA: "Contrainte non connue par l’IA",
  RISQUE_SECURITE: "Risque sécurité",
  MAUVAISE_PRIORITE_PRODUCTION: "Mauvaise priorité production",
  INFORMATION_INCORRECTE: "Information incorrecte",
  MEILLEURE_ALTERNATIVE: "Meilleure alternative",
  AUTRE: "Autre",
}

export const DECISION_STATUS_LABEL: Record<RecommendationDecisionType, string> = {
  PENDING: "En attente de décision",
  ACCEPTED: "Recommandation acceptée",
  MODIFIED: "Action modifiée par l’opérateur",
  REJECTED: "Recommandation rejetée",
}

export const FOLLOW_UP_STATUS_LABEL: Record<FollowUpStatus, string> = {
  OPEN: "Suivi ouvert",
  RESOLVED: "Suivi clôturé",
}
