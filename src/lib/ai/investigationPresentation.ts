import type { ConfidenceLevel, DiagnosisStatus, InvestigationError } from "@/lib/api/types/ai"
import type { InvestigationEntry } from "@/lib/store/useInvestigationStore"

export const CONFIDENCE_LABEL: Record<ConfidenceLevel, string> = { LOW: "Faible", MEDIUM: "Moyenne", HIGH: "Élevée" }

export const DIAGNOSIS_STATUS_LABEL: Record<DiagnosisStatus, string> = {
  CONFIRMED: "Cause confirmée",
  PROBABLE: "Cause probable",
  INCONCLUSIVE: "Cause non déterminée",
}

export function investigationStatus(entry?: InvestigationEntry): string {
  if (!entry || entry.phase === "absent") return "Analyse IA non lancée"
  if (entry.phase === "loading") return "Recherche d’une investigation existante…"
  if (entry.phase === "running") return "Analyse IA en cours"
  if (entry.phase === "error") return "Analyse indisponible"
  if (entry.result?.status === "FAILED") return "Analyse indisponible"
  if (entry.result?.status === "PENDING") return "Investigation en attente"
  const diagnosis = entry.result?.conclusion?.diagnosis_status
  if (diagnosis === "CONFIRMED") return "Cause confirmée"
  if (diagnosis === "PROBABLE") return "Cause probable — confirmation incomplète"
  if (diagnosis === "INCONCLUSIVE") return "Cause non déterminée"
  switch (entry.result?.status) {
    case "COMPLETED_WITH_UNCERTAINTY": return "Données insuffisantes / conclusion incertaine"
    case "COMPLETED": return "Analyse terminée"
    default: return "Analyse IA en cours"
  }
}

/** Never display arbitrary persisted exception messages (including older records). */
export function investigationFailure(error?: InvestigationError | null): string | undefined {
  if (!error) return undefined
  if (error.error_type === "ProviderTimeoutError") return "Délai de l’analyse IA dépassé. Investigation enregistrée en échec."
  if (error.error_type === "ProviderConfigurationError") return "Fournisseur IA non configuré."
  if (error.error_type === "ProviderAuthenticationError") return "Accès au fournisseur IA refusé. Vérifiez la configuration serveur."
  if (error.error_type === "ProviderModelError") return "Modèle IA indisponible ou incompatible. Vérifiez AI_MODEL."
  if (error.error_type === "ProviderRateLimitError") return "Fournisseur IA saturé (limite de débit). Réessayez dans un instant."
  if (error.error_type === "ProviderUnavailableError") return "Fournisseur IA temporairement indisponible."
  if (error.error_type === "ProviderNetworkError") return "Réseau du fournisseur IA injoignable."
  if (error.error_type === "ProviderResponseError") return "Réponse IA illisible. Investigation enregistrée en échec."
  if (error.stage === "analyze" || error.stage === "build_conclusion" || error.stage === "build_recommendation") return "Analyse IA échouée auprès du fournisseur. Consultez les journaux serveur."
  if (error.stage === "resolve_context") return "Contexte opérationnel indisponible."
  if (error.stage.includes("evidence")) return "Collecte des données opérationnelles échouée."
  return "Investigation échouée. Consultez les journaux serveur."
}
