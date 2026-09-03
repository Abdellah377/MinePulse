/** Actions IA view states. Optimization is hidden until a successful investigation. */

export const INVESTIGATION_REQUIRED_COPY =
  "Analysez cette alerte pour comprendre la situation avant d’afficher les recommandations et options d’optimisation."

export const FMS_DECISION_NOTE =
  "L’acceptation enregistre votre décision dans MinePulse. Aucune commande opérationnelle n’est exécutée automatiquement."

export const NO_CHANGE_ACTION_COPY =
  "Maintenir le plan actuel. Aucun changement utile n’a été identifié parmi les options évaluées."

export const NO_FEASIBLE_ACTION_COPY = "Aucun changement de dispatch faisable n’a été trouvé."

export const INSUFFICIENT_DATA_ACTION_COPY =
  "Les données opérationnelles disponibles ne permettent pas de produire une optimisation fiable."

export const OPTIMIZATION_UNAVAILABLE_COPY = "Optimisation indisponible"
export const OPTIMIZATION_UNAVAILABLE_DETAIL = "Le calcul n’a pas pu être terminé."
export const OPTIMIZATION_IN_PROGRESS_COPY = "Optimisation en cours"
export const OPTIMIZATION_STAGE_CONTEXT = "Analyse du contexte opérationnel..."

export type ActionsIaViewState =
  | "not_investigated"
  | "investigating"
  | "investigation_failed"
  | "complete_not_optimizable"
  | "optimizing"
  | "optimization_failed"
  | "complete_feasible"
  | "complete_no_change"
  | "complete_no_feasible"
  | "complete_insufficient"

export type ActionsIaViewInput = {
  hasInvestigation?: boolean
  entryPhase?: "loading" | "absent" | "running" | "ready" | "error" | null
  resultStatus?: string | null
  optimizationEligible: boolean
  runOutcome?: string | null
  workflowStatus?: string | null
  optimizing?: boolean
  optimizationFailed?: boolean
  hasDispatchSubject?: boolean
}

const SUCCESS_STATUSES = new Set(["COMPLETED", "COMPLETED_WITH_UNCERTAINTY"])

export function isSuccessfulInvestigation(
  entryPhase?: string | null,
  resultStatus?: string | null,
): boolean {
  if (entryPhase === "error") return false
  if (resultStatus === "FAILED") return false
  return SUCCESS_STATUSES.has(String(resultStatus ?? ""))
}

export function hasReusableOptimizationRun(outcome?: string | null): boolean {
  return Boolean(outcome) && outcome !== "ERROR"
}

export function hasLikelyDispatchScope(input: {
  equipmentId?: string | number | null
  alertType?: string | null
}): boolean {
  if (input.equipmentId != null && String(input.equipmentId).trim() !== "") return true
  const type = String(input.alertType ?? "")
  return type === "ROAD_CLOSED" || type === "ZONE_CLOSED"
}

export function shouldStartOptimizationRun(input: ActionsIaViewInput): boolean {
  if (!input.optimizationEligible) return false
  if (input.hasDispatchSubject === false) return false
  if (!isSuccessfulInvestigation(input.entryPhase, input.resultStatus)) return false
  if (input.optimizing) return false
  if (input.optimizationFailed) return false
  return !hasReusableOptimizationRun(input.runOutcome)
}

export function resolveActionsIaView(input: ActionsIaViewInput): ActionsIaViewState {
  const phase = input.entryPhase
  const status = input.resultStatus
  if (phase === "error" || status === "FAILED") return "investigation_failed"
  if (phase === "loading" || phase === "running" || status === "PENDING") return "investigating"
  if (!isSuccessfulInvestigation(phase, status)) {
    if (input.hasInvestigation && phase !== "absent") return "investigating"
    return "not_investigated"
  }
  if (!input.optimizationEligible || input.hasDispatchSubject === false) return "complete_not_optimizable"
  if (input.optimizing) return "optimizing"
  if (hasReusableOptimizationRun(input.runOutcome)) {
    if (input.workflowStatus === "NO_CHANGE_RECOMMENDED") return "complete_no_change"
    if (input.runOutcome === "NO_FEASIBLE_PLAN") return "complete_no_feasible"
    if (input.runOutcome === "INSUFFICIENT_DATA") return "complete_insufficient"
    if (input.runOutcome === "FEASIBLE") return "complete_feasible"
    if (input.runOutcome === "NOT_APPLICABLE" || input.runOutcome === "NOT_APPLICABLE_TO_DISPATCH") {
      return "complete_not_optimizable"
    }
    return "complete_feasible"
  }
  if (input.optimizationFailed) return "optimization_failed"
  return "optimizing"
}

export function actionsIaVisibility(state: ActionsIaViewState) {
  const investigated = state !== "not_investigated" && state !== "investigating" && state !== "investigation_failed"
  const showOptimization =
    state === "optimizing" ||
    state === "optimization_failed" ||
    state === "complete_feasible" ||
    state === "complete_no_change" ||
    state === "complete_no_feasible" ||
    state === "complete_insufficient"
  const showAction =
    state === "complete_not_optimizable" ||
    state === "complete_feasible" ||
    state === "complete_no_change" ||
    state === "complete_no_feasible" ||
    state === "complete_insufficient"
  return {
    showInvestiguer: state === "not_investigated" || state === "investigation_failed",
    showInvestigationProgress: state === "investigating",
    showAction,
    showOptimization,
    showImpact: state === "complete_feasible" || state === "complete_no_change",
    showDispatchOptions: showOptimization,
    showDecisionControls: showAction,
    showTechnicalDetails: showOptimization && investigated && state !== "optimizing" && state !== "optimization_failed",
    showRetry: state === "optimization_failed" || state === "complete_feasible" || state === "complete_no_change" || state === "complete_no_feasible" || state === "complete_insufficient",
  }
}
