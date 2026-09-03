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

export type ActionsIaViewState =
  | "not_investigated"
  | "investigating"
  | "investigation_failed"
  | "complete_not_optimizable"
  | "optimizing"
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

export function shouldStartOptimizationWorkflow(input: ActionsIaViewInput): boolean {
  if (!input.optimizationEligible) return false
  if (!isSuccessfulInvestigation(input.entryPhase, input.resultStatus)) return false
  if (input.optimizing) return false
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
  if (!input.optimizationEligible) return "complete_not_optimizable"
  if (input.optimizing || !hasReusableOptimizationRun(input.runOutcome)) return "optimizing"
  if (input.workflowStatus === "NO_CHANGE_RECOMMENDED") return "complete_no_change"
  if (input.runOutcome === "NO_FEASIBLE_PLAN") return "complete_no_feasible"
  if (input.runOutcome === "INSUFFICIENT_DATA") return "complete_insufficient"
  if (input.runOutcome === "FEASIBLE") return "complete_feasible"
  if (input.runOutcome === "NOT_APPLICABLE") return "complete_not_optimizable"
  return "optimizing"
}

export function actionsIaVisibility(state: ActionsIaViewState) {
  const investigated = state !== "not_investigated" && state !== "investigating" && state !== "investigation_failed"
  const showOptimization =
    state === "optimizing" ||
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
    showTechnicalDetails: showOptimization && investigated && state !== "optimizing",
  }
}
